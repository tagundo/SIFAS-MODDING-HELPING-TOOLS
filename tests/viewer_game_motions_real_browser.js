/* Original downloaded game assets through real HTTP/SSE/decryption/GLB/WebGL.
 * Supply REAL_GAME_MOTION_DIR with the private research samples; no game files
 * or successful API responses are embedded in this test. */
const assert = require('assert'), fs = require('fs'), os = require('os'), path = require('path'), net = require('net');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const root = path.resolve(process.env.VIEWER_REPO_ROOT || path.resolve(__dirname, '../..'));
const product = path.resolve(process.env.VIEWER_PRODUCT_DIR || path.join(root, 'modtools'));
const source = process.env.REAL_GAME_MOTION_DIR;
assert(source && fs.existsSync(path.join(source, 'ayumu-body.unity')), 'Set REAL_GAME_MOTION_DIR to the private original-game asset directory');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-real-game-motion-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', scope: 'Unmodified decrypted original Ayumu model with automatically completed face and original solo MV/pose/audio packs through actual product HTTP/SSE/Unity/GLB/WebGL; host Chromium, not a physical device. One explicitly marked recovery case replaces a failed face-status response.', samples: [] };
let server, browser;
async function boot() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  server = spawn(process.env.VIEWER_PYTHON || 'python3', ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: root, env: { ...process.env, PYTHONPATH: product + path.delimiter + root, SUKUSTA_DIR: source }, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stdout.pipe(stream); server.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw new Error('Product server exited ' + server.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return url; } catch (_) {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Product server did not become ready');
}
async function sample(page, time) {
  return page.evaluate(time => {
    const slider = document.getElementById('viewer-time'); slider.value = String(time); slider.dispatchEvent(new Event('input', { bubbles: true }));
    const state = ModelViewer.getState(), rig = state.rig;
    return { time: rig.time, clip: rig.selectedClip, bones: rig.bones.filter(bone => /(?:^|\/)(LeftUpLeg|RightUpLeg|Spine2|Head|LeftArm|RightArm|LeftEye1|RightEye1)$/.test(bone.name)),
      expressions: rig.expressions.filter(value => /EyeBlendShape|MouthBlendShape/.test(value.name)), visibleParts: rig.parts.filter(part => part.visible).map(part => part.name),
      audio: ViewerMotionAudio.getState(), probe: ModelViewer.renderProbe(33) };
  }, time);
}
(async () => {
  try {
    const url = await boot();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const context = await browser.newContext({ viewport: { width: 1500, height: 1050 }, deviceScaleFactor: 1 });
    await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    const page = await context.newPage(), errors = [], responses = [];
    page.setDefaultTimeout(180000); page.on('pageerror', error => { errors.push(String(error)); report.pageErrors = errors; });
    page.on('response', response => { if (/\/api\/viewer\/game\/motions\/(?:catalog|import)/.test(response.url())) responses.push({ path: new URL(response.url()).pathname, status: response.status() }); });
    await page.goto(url); await page.waitForFunction(() => document.getElementById('viewer-mesh-deleter') && window.ViewerMotionAudio);
    await page.evaluate(paths => { document.getElementById('viewer-auto-face').checked = true; return openModelViewer(paths); }, [path.join(source, 'ayumu-body.unity')]);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    const before = await page.evaluate(() => ({ camera: ModelViewer.getState().camera, body: ModelViewer.getAuthoringState(), triangles: ModelViewer.getState().sourceTriangles, faces: ModelViewer.getState().faces, clips: ModelViewer.getState().rig.clipNames }));
    assert.equal(before.faces.status, 'added', 'Body-only selection automatically completes the original face');
    await page.locator('#viewer-adjustments').evaluate(node => node.open = true);
    await page.locator('#viewer-game-motions').click();
    await page.waitForFunction(() => Array.from(document.getElementById('viewer-motion-character').options).some(option => option.value === '201'));
    assert.equal(await page.locator('#viewer-motion-region').inputValue(), 'gl', 'Korean UI defaults to GL');
    await page.locator('#viewer-motion-character').selectOption('201');
    await page.locator('#viewer-motion-category').selectOption('mv');
    await page.waitForFunction(() => !document.getElementById('viewer-motion-song-type').parentElement.hidden);
    await page.locator('#viewer-motion-song-type').selectOption('solo');
    await page.waitForFunction(() => Array.from(document.getElementById('viewer-game-motion-choice').options).some(option => option.value === 'mv:12002:1200201'));
    await page.locator('#viewer-game-motion-choice').selectOption('mv:12002:1200201');
    await page.locator('#viewer-motion-performer').selectOption('1');
    assert.equal(await page.locator('#viewer-motion-performer option').count(), 1, 'Original solo formation has one performer');
    await page.locator('#viewer-motion-linked-audio').check();
    await page.locator('#viewer-motion-import').click();
    await page.waitForFunction(() => !document.getElementById('viewer-game-motions-dialog').open && !ModelViewer.getState().loading && ModelViewer.getState().rig.selectedClip.startsWith('game-timeline:mv:mv:12002:1200201:1'));
    const after = await page.evaluate(() => ({ camera: ModelViewer.getState().camera, body: ModelViewer.getAuthoringState(), triangles: ModelViewer.getState().sourceTriangles, faces: ModelViewer.getState().faces, paths: ModelViewer.getState().loadedPaths, clips: ModelViewer.getState().rig.clipNames, internalClipCount: ModelViewer.getState().rig.internalClipCount, audio: ViewerMotionAudio.getState(), clip: ModelViewer.getState().rig.selectedClip }));
    assert.deepStrictEqual(after.camera, before.camera, 'Real dance import preserves camera');
    assert.deepStrictEqual(after.body, before.body, 'Real dance import preserves body authoring values');
    assert.equal(after.triangles, before.triangles, 'Selected dancer and facial banks add no geometry');
    assert.equal(after.faces.status, 'added', 'MV reload retains automatically completed original face');
    assert.deepStrictEqual(after.clips.filter(name => !before.clips.includes(name)), [after.clip], 'Original MV import exposes one composite and no raw dance or facial bank clips');
    assert(after.internalClipCount >= 33, 'Actual body and facial sources remain internal for synchronization');
    assert(after.audio.loaded && after.audio.tracks.some(track => track.cue === 'music_2002'), 'Original linked solo music decoded and attached');
    for (const time of [0, 4, 5, 20]) report.samples.push(await sample(page, time));
    assert(report.samples.every(value => value.bones.length >= 6), 'Real inspected dance bones are present');
    assert(new Set(report.samples.map(value => JSON.stringify(value.bones))).size > 1, 'Original dance changes actual skeleton transforms');
    assert(new Set(report.samples.map(value => JSON.stringify(value.expressions))).size > 1, 'Original authored mouth/eye tracks change actual morph weights');
    assert(report.samples.every(value => value.probe.ready && value.probe.glError === 0 && value.probe.nonBackgroundSamples > 0), 'Original mesh renders at every inspected dance time');
    await sample(page, 1); await page.locator('#viewer-play').click();
    await page.waitForFunction(() => ModelViewer.getState().rig.playing && !ViewerMotionAudio.getState().paused && ViewerMotionAudio.getState().time > 1);
    await page.locator('#viewer-play').click(); await page.waitForFunction(() => ViewerMotionAudio.getState().paused);
    report.playPauseAudio = await page.evaluate(() => ({ rig: ModelViewer.getMotionState().rig, audio: ViewerMotionAudio.getState() }));
    await page.screenshot({ path: path.join(evidence, 'original-solo-render.png') });
    // A genuine member voice action contains several body clips with their
    // original offsets/speeds, plus a delayed CRI cue and authored facial poses.
    await page.locator('#viewer-game-motions').click();
    await page.waitForFunction(() => Array.from(document.getElementById('viewer-motion-character').options).some(option => option.value === '1'));
    await page.locator('#viewer-motion-character').selectOption('1');
    await page.locator('#viewer-motion-category').selectOption('voice');
    await page.locator('#viewer-motion-search').fill('voice:1001014');
    await page.waitForFunction(() => Array.from(document.getElementById('viewer-game-motion-choice').options).some(option => option.value === 'voice:1001014'));
    await page.locator('#viewer-game-motion-choice').selectOption('voice:1001014');
    await page.locator('#viewer-motion-import').click();
    await page.waitForFunction(() => !document.getElementById('viewer-game-motions-dialog').open && !ModelViewer.getState().loading && ModelViewer.getState().rig.selectedClip === 'game-timeline:voice:voice:1001014:1');
    const voiceLoaded = await page.evaluate(() => ({ paths: ModelViewer.getState().loadedPaths, faces: ModelViewer.getState().faces, clips: ModelViewer.getState().rig.clipNames, audio: ViewerMotionAudio.getState(), triangles: ModelViewer.getState().sourceTriangles }));
    assert(voiceLoaded.paths.length <= 8, 'A second game motion replaces prior game inputs within the real viewer limit');
    assert.equal(voiceLoaded.triangles, before.triangles, 'Navigation motion and pose banks add no geometry');
    assert.equal(voiceLoaded.faces.status, 'added', 'Six imported voice/face banks retain automatically completed original face');
    assert.deepStrictEqual(voiceLoaded.clips.filter(name => !before.clips.includes(name)), ['game-timeline:voice:voice:1001014:1'], 'Four original voice segments and32facial poses add only one intentional motion choice');
    const cue = voiceLoaded.audio.tracks.find(track => track.cue === 'vo_ca_1000110014');
    assert(cue, 'The actual selected voice cue was decoded automatically');
    assert(Math.abs(cue.startTime - .7166666666666667) < 1e-8, 'The actual NaviVoiceTrack delay is preserved');
    report.voiceSamples = [];
    for (const time of [0, 1.5, 5, 9]) report.voiceSamples.push(await sample(page, time));
    assert(new Set(report.voiceSamples.map(value => JSON.stringify(value.bones))).size > 1, 'Original multi-clip navigation timeline changes actual skeleton transforms');
    assert(new Set(report.voiceSamples.map(value => JSON.stringify(value.expressions))).size > 1, 'Original navigation facial poses and speech change actual morph weights');
    await sample(page, .25); await page.locator('#viewer-play').click();
    await page.waitForFunction(() => ModelViewer.getState().rig.time > 1 && !ViewerMotionAudio.getState().paused);
    report.voicePlaying = await page.evaluate(() => ({ rig: ModelViewer.getMotionState().rig, audio: ViewerMotionAudio.getState() }));
    await page.locator('#viewer-play').click(); await page.waitForFunction(() => ViewerMotionAudio.getState().paused);
    assert(Math.abs(report.voicePlaying.audio.time - (report.voicePlaying.rig.time - cue.startTime)) < .25, 'Automatic voice follows the original delayed playhead');
    await page.screenshot({ path: path.join(evidence, 'original-navigation-voice-render.png') });
    report.voiceLoaded = voiceLoaded;
    await page.evaluate(additional => ModelViewer.addMotion([additional]), path.join(source, 'ayumu-animations1.unity'));
    report.eightSelected = await page.evaluate(() => ({ paths: ModelViewer.getState().loadedPaths,
      faces: ModelViewer.getState().faces, clips: ModelViewer.getState().rig.clipNames, selected: ModelViewer.getState().rig.selectedClip, triangles: ModelViewer.getState().sourceTriangles, probe: ModelViewer.renderProbe(33) }));
    assert.equal(report.eightSelected.paths.length, 8, 'Eight explicit body/animation inputs are supported');
    assert.equal(report.eightSelected.faces.status, 'added', 'Automatic face has a separate dependency budget at eight explicit inputs');
    assert.equal(report.eightSelected.triangles, before.triangles, 'Eight inputs retain the complete original face geometry');
    assert.deepStrictEqual(report.eightSelected.clips, voiceLoaded.clips, 'Adding a raw original eye bank creates no stray motion choices');
    assert.equal(report.eightSelected.selected, 'game-timeline:voice:voice:1001014:1', 'A manual auxiliary import preserves the selected complete voice motion');
    assert(report.eightSelected.probe.ready && report.eightSelected.probe.glError === 0 && report.eightSelected.probe.nonBackgroundSamples > 0);
    await sample(page, 1); await page.locator('#viewer-play').click();
    await page.waitForFunction(() => ModelViewer.getMotionState().rig.time > 1.4 && !ViewerMotionAudio.getState().paused && ViewerMotionAudio.getState().time > .1);
    report.audioAfterManualReload = await page.evaluate(() => ({ rig: ModelViewer.getMotionState().rig, audio: ViewerMotionAudio.getState() }));
    await page.locator('#viewer-play').click(); await page.waitForFunction(() => ViewerMotionAudio.getState().paused);
    // Failure injection is limited to this recovery check. The prior displayed
    // model and its complete automatic face are genuine converted assets.
    const recoveryBefore = await page.evaluate(() => ({ id: ModelViewer.getState().modelId, camera: ModelViewer.getState().camera,
      paths: ModelViewer.getState().loadedPaths, faces: ModelViewer.getState().faces, triangles: ModelViewer.getState().sourceTriangles }));
    await page.route('**/api/viewer/prepare', async route => {
      const response = await route.fetch(); assert(response.ok(), 'Recovery check starts with actual successful preparation');
      const result = await response.json(); result.faces = { ...result.faces, status: 'unavailable', added: 0 };
      await route.fulfill({ response, json: result });
    });
    const recoveryResult = await page.evaluate(async additional => {
      try { await ModelViewer.addMotion([additional], { replaceGame: true }); return { accepted: true }; }
      catch (error) { return { accepted: false, error: String(error.message) }; }
    }, path.join(source, 'ayumu-animations2.unity'));
    assert.equal(recoveryResult.accepted, false, 'Incomplete face response rejects the motion before replacing the model');
    const recoveryAfter = await page.evaluate(() => ({ id: ModelViewer.getState().modelId, camera: ModelViewer.getState().camera,
      paths: ModelViewer.getState().loadedPaths, faces: ModelViewer.getState().faces, triangles: ModelViewer.getState().sourceTriangles }));
    assert.deepStrictEqual(recoveryAfter, recoveryBefore, 'Failed automatic-face reconstruction keeps actual model, face, camera and paths');
    await page.unroute('**/api/viewer/prepare');
    report.faceRecovery = { injectedFaceFailure: true, result: recoveryResult, before: recoveryBefore, after: recoveryAfter };
    // Original raw bundles also go through the normal manual AddMotion path.
    // A camera timeline or a facial pose bank must not masquerade as a dance.
    await page.evaluate(body => openModelViewer([body]), path.join(source, 'ayumu-body.unity'));
    const manualBase = await page.evaluate(() => ({ clips: ModelViewer.getState().rig.clipNames, triangles: ModelViewer.getState().sourceTriangles }));
    report.manualOriginal = [];
    for (const filename of ['group-main.unity', 'ayumu-animations1.unity', 'ayumu-animations2.unity']) {
      await page.evaluate(additional => ModelViewer.addMotion([additional]), path.join(source, filename));
      const state = await page.evaluate(() => ({ clips: ModelViewer.getState().rig.clipNames, triangles: ModelViewer.getState().sourceTriangles, selected: ModelViewer.getState().rig.selectedClip }));
      assert.deepStrictEqual(state.clips, manualBase.clips, 'Original raw camera/facial bundle contributes no character motion choices: ' + filename);
      assert.equal(state.triangles, manualBase.triangles, 'Raw camera/facial bundle changes no displayed geometry');
      report.manualOriginal.push({ filename, ...state });
    }
    await page.locator('#viewer-motion').selectOption('');
    await page.evaluate(additional => ModelViewer.addMotion([additional]), path.join(source, 'solo-dance.unity'));
    const manualDance = await page.evaluate(() => ({ clips: ModelViewer.getState().rig.clipNames, selected: ModelViewer.getState().rig.selectedClip }));
    const danceChoices = manualDance.clips.filter(name => !manualBase.clips.includes(name));
    assert.deepStrictEqual(danceChoices, ['ch0201_so2002'], 'The original raw compatible character dance is an explicit selectable choice');
    assert.equal(manualDance.selected, '', 'Loading raw body alternatives preserves the selected saved pose');
    await page.locator('#viewer-motion').selectOption(danceChoices[0]);
    const manualFrames = [await sample(page, 0), await sample(page, 20)];
    assert.notDeepStrictEqual(manualFrames[0].bones, manualFrames[1].bones, 'Original manually selected raw character clip animates real model bones');
    report.manualDance = manualDance;
    assert.deepStrictEqual(errors, []); report.before = before; report.after = after; report.responses = responses; report.status = 'PASS';
    await context.close();
  } catch (error) { report.status = 'FAIL'; report.error = error.stack || String(error); process.exitCode = 1; }
  finally {
    if (browser) await browser.close(); if (server && server.exitCode === null) server.kill('SIGTERM');
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error }));
  }
})();
