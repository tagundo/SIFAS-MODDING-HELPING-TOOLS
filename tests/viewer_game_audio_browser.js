/* Actual private game voice through native decoding, HTTP media and WebAudio. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');
const net = require('net');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const repo = path.resolve(__dirname, '../..'), product = path.join(repo, 'modtools');
const python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const acb = process.env.SIFAS_TEST_ACB, awb = process.env.SIFAS_TEST_AWB, timeline = process.env.SIFAS_TEST_TIMELINE;
if (!acb || !awb || !timeline) { console.log('SKIP: provide private SIFAS_TEST_ACB/AWB/TIMELINE for actual game voice QA.'); process.exit(0); }
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-real-audio-library-'));
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-real-audio-'));
const source = path.join(library, 'extracted/3d_model/neutral.unity'), descriptor = path.join(evidence, 'descriptor.json');
fs.mkdirSync(path.dirname(source), { recursive: true }); fs.mkdirSync(path.join(library, 'packs'), { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
fs.copyFileSync(process.env.VIEWER_AUDIO_FIXTURE || path.join(__dirname, 'fixtures/viewer_persistence.unity'), source);
// Catalog pack IDs from the exact private voice selected for this integration.
fs.copyFileSync(acb, path.join(library, 'packs/j1v3t5')); fs.copyFileSync(awb, path.join(library, 'packs/kwxlry'));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const logs = fs.createWriteStream(path.join(evidence, 'server.log'));
  const server = spawn(python, [path.join(__dirname, 'game_motion_audio_browser_server.py'), '--port', String(port), '--repo', repo,
    '--library', library, '--timeline', timeline, '--descriptor', descriptor], { cwd: repo,
    env: { ...process.env, PYTHONPATH: [repo, product].join(path.delimiter), SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stdout.pipe(logs); server.stderr.pipe(logs);
  let browser, page;
  try {
    const url = 'http://127.0.0.1:' + port;
    for (let n = 0; n < 200; n++) { if (server.exitCode !== null) throw new Error(fs.readFileSync(path.join(evidence, 'server.log'), 'utf8')); try { if ((await fetch(url + '/api/tools')).ok) break; } catch (_) {} await wait(100); }
    const audioDescriptor = JSON.parse(fs.readFileSync(descriptor, 'utf8'));
    assert.equal(audioDescriptor.tracks[0].cue, 'vo_ca_1000110014'); assert.equal(audioDescriptor.tracks[0].startTime, .7166666666666667);
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    page = await browser.newPage({ viewport: { width: 1360, height: 1000 } }); const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.addInitScript(() => {
      window.__mediaTrace = [];
      function record(kind, media, error) { if (__mediaTrace.length >= 600) return;
        __mediaTrace.push({kind,time:performance.now(),mediaTime:media.currentTime,paused:media.paused,seeking:media.seeking,
          rig:window.ModelViewer&&ModelViewer.getMotionState().rig,error:error&&String(error),stack:new Error().stack}); }
      const pause=HTMLMediaElement.prototype.pause,play=HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.pause=function(){record('pause',this);return pause.call(this);};
      HTMLMediaElement.prototype.play=function(){record('play',this);const result=play.call(this);if(result&&result.then)result.then(()=>record('playing',this),error=>record('play-error',this,error));return result;};
    });
    await page.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; openModelViewer([source]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
    await page.locator('#viewer-adjustments').evaluate(el => { el.open = true; });
    const clip = await page.locator('#viewer-motion option').evaluateAll(options => options.find(option => option.value).value);
    await page.locator('#viewer-motion').selectOption(clip);
    if (process.env.AUDIO_STALL_QA) await page.evaluate(() => {
      const physics = ModelViewer.getState().rig.physics;
      if (!physics.nativeAvailable || physics.mode !== 'game' || ModelViewer.getMotionState().rig.duration < 8)
        throw new Error('Stall QA requires the declared long native-physics fixture');
      ['viewer-physics-bones', 'viewer-physics-colliders'].forEach(id => { const input=document.getElementById(id); if(!input.checked) input.click(); });
    });
    await page.evaluate(({ descriptor, clip }) => ViewerMotionAudio.load(descriptor, { clipNames: [clip] }), { descriptor: audioDescriptor, clip });
    await page.waitForFunction(() => ViewerMotionAudio.getState().tracks[0].readyState >= 2);
    await page.evaluate(() => {
      const audio = document.querySelector('.viewer-motion-audio-player');
      const context = new AudioContext(), analyser = context.createAnalyser(); analyser.fftSize = 2048;
      context.createMediaElementSource(audio).connect(analyser); analyser.connect(context.destination);
      window.__audioQa = { context, analyser, bytes: new Float32Array(analyser.fftSize), peak: 0 };
    });
    await page.locator('#viewer-play').click();
    await page.evaluate(() => __audioQa.context.resume());
    await page.waitForFunction(() => ModelViewer.getMotionState().rig.time > .2);
    assert.equal(await page.evaluate(() => ViewerMotionAudio.getState().paused), true, 'voice waits for original0.7167s timeline start');
    await page.waitForFunction(() => {
      const q = __audioQa; q.analyser.getFloatTimeDomainData(q.bytes);
      const rms = Math.sqrt(q.bytes.reduce((sum, x) => sum + x * x, 0) / q.bytes.length); q.peak = Math.max(q.peak, rms);
      return q.peak > .002;
    });
    const live = await page.evaluate(() => ({ audio: ViewerMotionAudio.getState(), motion: ModelViewer.getMotionState().rig, rms: __audioQa.peak }));
    assert(!live.audio.paused && !live.audio.blocked); assert(live.rms > .002, 'actual browser rendered nonzero voice samples');
    let stalled = null;
    if (process.env.AUDIO_STALL_QA) {
      const before = await page.evaluate(() => {
        window.__renderStalls=0;window.__stallTimer=setInterval(()=>{__renderStalls++;const end=performance.now()+220;while(performance.now()<end){}},400);
        return {audio:ViewerMotionAudio.getState(),physics:ModelViewer.getState().rig.physics};
      });
      await wait(3000);
      const stoppedAt = await page.evaluate(() => {clearInterval(__stallTimer);return ModelViewer.getState().rig.physics.solver.totalNativeSteps;});
      // The media thread keeps running inside the injected blocked frame.
      // Observe the next actually accepted physics frame, not the old pose
      // immediately before its queued render callback can sample that clock.
      await page.waitForFunction(steps=>ModelViewer.getState().rig.physics.solver.totalNativeSteps>steps,stoppedAt);
      const after = await page.evaluate(() => {return {audio:ViewerMotionAudio.getState(),motion:ModelViewer.getMotionState().rig,
        physics:ModelViewer.getState().rig.physics,stalls:__renderStalls};});
      assert(after.stalls>=5);assert.equal(after.audio.tracks[0].seeks,before.audio.tracks[0].seeks,'Actual 3D render stalls must not seek original voice');
      assert(Math.abs(after.audio.time-(after.motion.time-.7166666666666667))<.10,'Actual native-frame motion follows continuous voice');
      assert(after.physics.solver.totalNativeSteps>before.physics.solver.totalNativeSteps,'Original physics continues once per accepted frame');
      stalled={before,after};
    }
    await page.locator('#viewer-play').click();
    await page.waitForFunction(() => ViewerMotionAudio.getState().paused);
    const paused = await page.evaluate(() => ViewerMotionAudio.getState().time); await wait(150);
    assert(Math.abs(await page.evaluate(() => ViewerMotionAudio.getState().time) - paused) < .03);
    await page.locator('#viewer-time').fill('1.5'); await page.locator('#viewer-time').dispatchEvent('input');
    await page.waitForFunction(() => Math.abs(ViewerMotionAudio.getState().time - (1.5 - .7166666666666667)) < .12);
    await page.locator('#viewer-motion-audio-controls').evaluate(el => { el.open = true; });
    await page.locator('#viewer-motion-audio-muted').check();
    await page.locator('#viewer-motion-audio-volume').fill('0.4'); await page.locator('#viewer-motion-audio-volume').dispatchEvent('input');
    const preferences = await page.evaluate(() => ViewerMotionAudio.getState()); assert(preferences.muted); assert.equal(preferences.volume, .4);
    await page.locator('#viewer-time').fill('0.1'); await page.locator('#viewer-time').dispatchEvent('input');
    await page.waitForFunction(() => ViewerMotionAudio.getState().paused && ViewerMotionAudio.getState().time < .02);
    assert.deepStrictEqual(errors, []);
    await page.screenshot({ path: path.join(evidence, 'game-audio-ko.png'), fullPage: true });
    const report={ status: 'PASS', evidence, originalCue: audioDescriptor.tracks[0].cue, timelineStart: audioDescriptor.tracks[0].startTime,
      sampleRate:audioDescriptor.tracks[0].sampleRate,channels:audioDescriptor.tracks[0].channels,frames:audioDescriptor.tracks[0].frames,
      rms: live.rms, pauseSeekMuteVolume: true,stalled };
    fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  } catch (error) {
    if (page) {
      const diagnostic = await page.evaluate(() => ({ audio: ViewerMotionAudio.getState(), motion: ModelViewer.getMotionState(),
        context: window.__audioQa && { state: __audioQa.context.state, peak: __audioQa.peak },mediaTrace:window.__mediaTrace })).catch(() => null);
      fs.writeFileSync(path.join(evidence, 'failure-state.json'), JSON.stringify(diagnostic, null, 2));
      await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }).catch(() => {});
    }
    throw error;
  } finally { if (browser) await browser.close(); server.kill(); logs.end(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
