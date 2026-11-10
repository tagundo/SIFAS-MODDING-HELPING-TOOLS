/* Audio selection must not clone every retained body/facial timeline. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const generated = fixture();
generated.rig.clips[0].sourceHash = 'lookup-body';
generated.rig.clips[0].sourceName = 'lookup-body';
const audio = position => ({ version: 1, warnings: ['Original cue'], tracks: [{
  url: '/api/viewer/game/motions/audio/' + String(position).repeat(32) + '.wav', cue: 'cue-' + position,
  startTime: .2, offset: .25, playDuration: .6, playbackRate: .8,
  envelope: { kind: 'rms_mouth_openness', step: .04, values: [.1, .3, .2] }
}] });
const descriptors = [1, 2, 3].map(position => ({ version: 2, category: 'mv', motion: 'lookup',
  performerPosition: position, label: 'Generated performer ' + position, duration: 1,
  bodySegments: [{ sourceHash: 'lookup-body', sourceName: 'lookup-body', start: 0, duration: 1, clipIn: 0, timeScale: 1 }],
  facialClips: [], clipSources: [], facial: { duration: 1, events: [] },
  audio: position === 3 ? null : audio(position) }));
descriptors.push({ ...descriptors[0], category: 'voice', motion: 'voice-lookup', performerPosition: 1, audio: audio(4) });
generated.rig.motionTimelines = descriptors;
const wave = Buffer.alloc(44 + 44100);
wave.write('RIFF'); wave.writeUInt32LE(wave.length - 8, 4); wave.write('WAVEfmt ', 8);
wave.writeUInt32LE(16, 16); wave.writeUInt16LE(1, 20); wave.writeUInt16LE(1, 22);
wave.writeUInt32LE(22050, 24); wave.writeUInt32LE(44100, 28); wave.writeUInt16LE(2, 32);
wave.writeUInt16LE(16, 34); wave.write('data', 36); wave.writeUInt32LE(44100, 40);
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'motion-audio-lookup-'));
fs.mkdirSync(evidence, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } }), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.addInitScript(() => {
      localStorage.setItem('sifas_lang', 'en');
      Object.defineProperty(window, 'ViewerRig', { configurable: true, set(api) {
        const create = api.create;
        api.create = function () { const rig = create.apply(this, arguments); window.__lookupRig = rig; return rig; };
        Object.defineProperty(window, 'ViewerRig', { configurable: true, writable: true, value: api });
      } });
    });
    await page.route('**/api/viewer/prepare', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({
      id: 'lookup-fixture', url: '/api/viewer/model/lookup-fixture.glb',
      stats: { meshes: 1, vertices: 3, triangles: 1, materials: 1, textures: 0 }, warnings: [], rig: generated.rig
    }) }));
    await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ contentType: 'model/gltf-binary', body: generated.glb }));
    await page.route('**/api/viewer/game/motions/audio/*.wav', route => route.fulfill({ contentType: 'audio/wav', body: wave }));
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
    await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(() => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer(['/generated/audio-lookup.unity']); });
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    await page.locator('#viewer-adjustments').evaluate(element => { element.open = true; });
    const checked = await page.evaluate(expected => {
      const rig = window.__lookupRig, key = position => 'game-timeline:mv:lookup:' + position;
      const same = (a, b) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw Error('Audio/export changed'); };
      same(rig.getMotionTimelines(), expected);
      same(rig.getMotionAudio(key(1)), expected[0].audio);
      same(rig.getMotionAudio(key(2)), expected[1].audio);
      same(rig.getMotionAudio('game-timeline:voice:voice-lookup:1'), expected[3].audio);
      for (const name of [null, undefined, {}, 1, '', 'missing', key(3)]) {
        if (rig.getMotionAudio(name) !== null) throw Error('Unknown or absent audio must return null');
      }
      const copy = rig.getMotionAudio(key(1)); copy.tracks[0].offset = 99; copy.tracks[0].envelope.values[0] = 99;
      copy.warnings.push('mutated');
      same(rig.getMotionAudio(key(1)), expected[0].audio);
      const full = rig.getMotionTimelines(); full[0].bodySegments[0].start = 99; full[0].audio.tracks[0].cue = 'mutated';
      same(rig.getMotionTimelines(), expected);
      const whole = rig.getMotionTimelines, selected = rig.getMotionAudio;
      window.__wholeCalls = 0; window.__selectedCalls = 0; window.__audioLoads = [];
      rig.getMotionTimelines = function () { window.__wholeCalls++; return whole.apply(this, arguments); };
      rig.getMotionAudio = function () { window.__selectedCalls++; return selected.apply(this, arguments); };
      window.__wholeLookup = rig.getMotionTimelines; window.__selectedLookup = rig.getMotionAudio;
      const load = ViewerMotionAudio.load;
      ViewerMotionAudio.load = function (descriptor, options) {
        window.__audioLoads.push(JSON.parse(JSON.stringify(descriptor))); return load.call(this, descriptor, options);
      };
      return { descriptors: expected.length, invalidOrAbsent: 7, nestedCopyAndFullExportIndependent: true };
    }, descriptors);
    await page.locator('#viewer-motion').selectOption('game-timeline:mv:lookup:1');
    assert.deepStrictEqual(await page.evaluate(() => __audioLoads.at(-1)), descriptors[0].audio);
    assert.equal(await page.evaluate(() => __wholeCalls), 0);
    assert.equal(await page.evaluate(() => __selectedCalls), 1);
    await page.locator('#viewer-motion').selectOption('game-timeline:mv:lookup:2');
    assert.deepStrictEqual(await page.evaluate(() => __audioLoads.at(-1)), descriptors[1].audio);
    assert.equal(await page.evaluate(() => __wholeCalls), 0);
    await page.locator('#viewer-motion').selectOption('game-timeline:mv:lookup:3');
    assert.equal(await page.evaluate(() => ViewerMotionAudio.getState().loaded), false);
    // Existing embedders/test doubles can expose only the old full export.
    await page.evaluate(() => { delete __lookupRig.getMotionAudio; });
    await page.locator('#viewer-motion').selectOption('game-timeline:mv:lookup:1');
    assert.deepStrictEqual(await page.evaluate(() => __audioLoads.at(-1)), descriptors[0].audio);
    assert.equal(await page.evaluate(() => __wholeCalls), 1);
    // The original metadata fallback remains available without either getter.
    await page.evaluate(() => { delete __lookupRig.getMotionTimelines; });
    await page.locator('#viewer-motion').selectOption('game-timeline:mv:lookup:2');
    assert.deepStrictEqual(await page.evaluate(() => __audioLoads.at(-1)), descriptors[1].audio);
    assert.equal(await page.evaluate(() => __wholeCalls), 1);
    await page.evaluate(() => { __lookupRig.getMotionAudio = __selectedLookup; __lookupRig.getMotionTimelines = __wholeLookup; });
    await page.locator('#viewer-motion').selectOption('game-timeline:mv:lookup:1');
    assert.deepStrictEqual(await page.evaluate(() => __audioLoads.at(-1)), descriptors[0].audio);
    assert.equal(await page.evaluate(() => __wholeCalls), 1);
    assert.deepStrictEqual(await page.evaluate(() => __lookupRig.getMotionTimelines()), descriptors);
    assert.deepStrictEqual(errors, []);
    const report = { status: 'PASS', scope: 'Generated skinned fixture; actual ViewerRig, viewer UI and audio binding',
      ...checked, selectiveUiBinding: true, legacyGetterAndMetadataFallbacks: true, errors };
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
