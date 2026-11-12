/* Actual Unity -> HTTP -> GLTF -> WebGL scaling, with stable operation counts.
 * RIG_SOURCE_OVERRIDE + MEASURE_BASELINE permit comparison to an archived rig
 * implementation; normal runs require bounded resolutions and active actions.
 * All fixture sources are original neutral data and checked byte-for-byte.
 */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-many-clips-proof-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-many-clips-library-')), models = path.join(library, 'extracted/3d_model');
const label = process.env.LABEL || 'many-clips', baseline = process.env.MEASURE_BASELINE === '1';
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const fixtures = JSON.parse(execFileSync(python, ['-B', '-c', `import json,sys;sys.path.insert(0,'tests');from test_viewer_motion_library import make_many_motion_library_fixture;print(json.dumps(make_many_motion_library_fixture(sys.argv[1])))`, models], { cwd: product, encoding: 'utf8' }));
const hashes = Object.fromEntries(Object.values(fixtures).map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')]));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, label + '-server.log'));
  const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw new Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, stream }; } catch (_) {} await wait(100); }
  child.kill(); throw new Error('Product server did not become ready');
}
async function ready(page) { await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading); }
async function main() {
  let server, browser; const errors = [], report = { label, baseline, cases: [] };
  try {
    server = await start();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--js-flags=--expose-gc'] });
    report.browser = { version: browser.version(), host: 'Linux Chromium with macOS host bridge stub', renderer: 'ANGLE SwiftShader' };
    const context = await browser.newContext({ viewport: { width: 1360, height: 1000 } }), page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await context.addInitScript(() => { localStorage.setItem('sifas_lang', 'en'); window.ElichikaDesktop = { platform: 'macos', version: 1, capabilities: [] }; });
    page.setDefaultTimeout(120000); page.on('pageerror', error => errors.push(String(error.stack || error)));
    if (process.env.RIG_SOURCE_OVERRIDE) await page.route('**/static/viewer-rig.js*', route => route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(process.env.RIG_SOURCE_OVERRIDE, 'utf8') }));
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(() => {
      document.getElementById('viewer-auto-face').checked = false;
      window.__manyClips = { find: 0, bindings: 0, rig: [], timelineCount: 0 };
      const find = THREE.PropertyBinding.findNode, binding = THREE.PropertyBinding.create, Mixer = THREE.AnimationMixer, create = ViewerRig.create;
      THREE.PropertyBinding.findNode = function () { __manyClips.find++; return find.apply(this, arguments); };
      THREE.PropertyBinding.create = function () { __manyClips.bindings++; return binding.apply(this, arguments); };
      THREE.AnimationMixer = function (root) { const mixer = new Mixer(root); __manyClips.mixer = mixer; return mixer; };
      THREE.AnimationMixer.prototype = Mixer.prototype;
      ViewerRig.create = function (root, animations, info, options) {
        // Exercise retained timeline initialization against actual converted
        // source identities. This supplies fixture descriptors, not fake clips.
        if (__manyClips.timelineCount) info = Object.assign({}, info, { motionTimelines: info.clips.filter(c => c.name.startsWith('Stress motion')).slice(0, __manyClips.timelineCount).map((clip, index) => ({
          version: 2, category: 'mv', motion: 'stress:' + index, performerPosition: 1, label: 'Composed stress ' + index,
          bodySegments: [{ sourceHash: clip.sourceHash, sourceName: clip.sourceName, start: 0, duration: clip.duration }],
          facialClips: [], facial: { duration: clip.duration, events: [] }, physics: { profile: 'live', safeSwingBoneKnown: true, safeSwingBone: true }
        })) });
        const start = performance.now(), findBefore = __manyClips.find, bindingBefore = __manyClips.bindings;
        const rig = create(root, animations, info, options);
        __manyClips.currentRig = rig;
        __manyClips.rig.push({ ms: performance.now() - start, find: __manyClips.find - findBefore, bindings: __manyClips.bindings - bindingBefore });
        return rig;
      };
    });
    await page.evaluate(source => openModelViewer([source]), fixtures.body_a); await ready(page);
    for (const count of [10, 100, 400]) {
      if (await page.evaluate(() => ModelViewer.getState().motionLibraryPaths.length)) { await page.locator('#viewer-clear-motion-library').evaluate(e => e.click()); await ready(page); }
      const start = Date.now(); await page.evaluate(source => ModelViewer.addMotion([source]), fixtures['bank_' + count]); await ready(page);
      const loadMs = Date.now() - start, creation = await page.evaluate(() => __manyClips.rig[__manyClips.rig.length - 1]);
      const switched = await page.evaluate(async count => {
        const select = document.getElementById('viewer-motion'), names = Array.from(select.options).map(o => o.value).filter(n => n.startsWith('Stress motion'));
        if (names.length !== count) throw new Error('Expected ' + count + ' motions, got ' + names.length);
        const mutations = [], observer = new MutationObserver(records => mutations.push(...records)); observer.observe(select, { childList: true, subtree: true });
        const started = performance.now(); let firstPose;
        for (const name of names) {
          select.value = name; select.dispatchEvent(new Event('change', { bubbles: true }));
          const slider = document.getElementById('viewer-time'); slider.value = '.75'; slider.dispatchEvent(new Event('input', { bubbles: true }));
          if (!firstPose) firstPose = ModelViewer.getState().rig.bones.find(b => b.name.includes('LeftUpLeg')).quaternion;
        }
        const switchMs = performance.now() - started; await new Promise(resolve => requestAnimationFrame(resolve)); observer.disconnect();
        const state = ModelViewer.getState(), mixer = __manyClips.mixer;
        if (window.gc) gc();
        return { switchMs, listMutations: mutations.length, mixer: { actions: mixer.stats.actions.total, bindings: mixer.stats.bindings.total, activeBindings: mixer.stats.bindings.inUse }, heap: performance.memory && performance.memory.usedJSHeapSize,
          firstPose, lastPose: state.rig.bones.find(b => b.name.includes('LeftUpLeg')).quaternion, clipCount: state.rig.clipNames.length, selectedClip: state.rig.selectedClip, time: state.rig.time, physicsMode: state.rig.physics.mode };
      }, count);
      await cdp.send('HeapProfiler.collectGarbage');
      const heap = await cdp.send('Runtime.getHeapUsage');
      switched.heap = heap.usedSize;
      switched.heapMeasurement = 'CDP Runtime.getHeapUsage after explicit garbage collection';
      assert.equal(switched.listMutations, 0, 'changing motions must not rebuild their DOM list');
      assert(switched.firstPose.some((value, index) => Math.abs(value - switched.lastPose[index]) > .01), 'different real imported poses reach the bound skeleton');
      if (!baseline) { assert(creation.find <= 4, 'classification resolves shared track paths once per model'); assert.equal(switched.mixer.actions, 1, 'visited clips release inactive mixer actions'); }
      const frame = await page.evaluate(async () => {
        const slider = document.getElementById('viewer-time'); slider.value = '0'; slider.dispatchEvent(new Event('input', { bubbles: true })); document.getElementById('viewer-play').click();
        let last; const intervals = [], playheads = [];
        for (let i = 0; i < 32; i++) await new Promise(resolve => requestAnimationFrame(now => { if (last !== undefined) intervals.push(now - last); last = now; playheads.push(__manyClips.currentRig.getPlaybackState().time); resolve(); }));
        if (__manyClips.currentRig.getPlaybackState().playing) document.getElementById('viewer-play').click();
        return { intervals, playheads, probe: ModelViewer.renderProbe(23) };
      });
      assert(frame.playheads.some(value => value > 0), 'actual display frames advance the selected motion');
      assert(frame.probe.ready && frame.probe.glError === 0 && frame.probe.chromaticSamples > 0, 'real WebGL renders a colored posed model');
      report.cases.push({ count, loadMs, creation, switched, frame });
    }
    // Retained timelines must not cause another all-bank classification pass
    // for every descriptor, and their sources remain internal choices.
    await page.evaluate(source => { __manyClips.timelineCount = 16; return ModelViewer.open([source]); }, fixtures.body_b); await ready(page);
    const composed = await page.evaluate(() => {
      const state = ModelViewer.getState(), select = document.getElementById('viewer-motion'), name = Array.from(select.options).find(o => o.textContent === 'Composed stress 15').value;
      select.value = name; select.dispatchEvent(new Event('change', { bubbles: true }));
      const slider = document.getElementById('viewer-time'); slider.value = '.75'; slider.dispatchEvent(new Event('input', { bubbles: true }));
      return { creation: __manyClips.rig[__manyClips.rig.length - 1], state: ModelViewer.getState(), composedCount: Array.from(select.options).filter(o => o.value.startsWith('game-timeline:')).length };
    });
    assert.equal(composed.composedCount, 16); assert.equal(composed.state.rig.internalClipCount, 16);
    assert(composed.state.rig.selectedClip.includes('stress:15')); assert.equal(composed.state.rig.time, .75);
    if (!baseline) assert(composed.creation.find <= 40, 'batch timeline registration must classify the bank only once');
    assert.deepStrictEqual(composed.state.motionLibraryPaths, [fixtures.bank_400]); assert.deepStrictEqual(composed.state.loadedPaths, [fixtures.body_b]);
    report.timelines = { creation: composed.creation, count: composed.composedCount, internalClipCount: composed.state.rig.internalClipCount, selectedClip: composed.state.rig.selectedClip };
    await page.locator('#viewer-stage canvas').screenshot({ path: path.join(evidence, label + '-400-clips.png') });
    assert.deepStrictEqual(errors, []);
    for (const [file, hash] of Object.entries(hashes)) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), hash, 'source immutable: ' + file);
    report.sources = Object.entries(hashes).map(([file, hash]) => ({ name: path.basename(file), before: hash, after: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') }));
    report.status = 'PASS'; report.errors = errors;
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally {
    if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); }
    fs.rmSync(library, { recursive: true, force: true });
    fs.writeFileSync(path.join(evidence, label + '.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
