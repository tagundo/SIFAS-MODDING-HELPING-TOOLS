/* Optional original game source through the actual HTTP/Unity/WebGL UI. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), os = require('os'), net = require('net');
const {spawn} = require('child_process'), {chromium} = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product), source = process.env.REAL_GAME_MOTION_DIR;
assert(source && fs.existsSync(path.join(source, 'ayumu-face.unity')), 'Set REAL_GAME_MOTION_DIR to the private original sample directory');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-original-gaze-'));
fs.mkdirSync(evidence, {recursive: true});
const report = {status: 'RUNNING', scope: 'Unmodified Ayumu body/face and receipt-verified original soloMV through product HTTP/Unity/GLB/WebGL; source-derived eye-contact targets and actual UI. Preview camera, not original MV stage camera.'};
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function show(locator) { await locator.evaluate(node => { for (let p = node.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; }); await locator.scrollIntoViewIfNeeded(); return locator; }
let server, browser;
async function main() {
 try {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  server = spawn(process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python', ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
   {cwd: repo, env: {...process.env, PYTHONPATH: [product, repo, path.join(product, 'tests')].join(path.delimiter), SUKUSTA_DIR: source}, stdio: ['ignore', 'pipe', 'pipe']});
  server.stdout.pipe(stream); server.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  let ready = false; for (let i = 0; i < 150; i++) { if (server.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) { ready = true; break; } } catch (_) {} await delay(100); }
  assert(ready, 'Product server starts');
  browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), errors = []; page.setDefaultTimeout(180000);
  page.on('pageerror', error => errors.push(String(error.stack || error))); let prepared;
  page.on('response', async response => { if (response.url().endsWith('/api/viewer/prepare') && response.ok()) prepared = await response.json(); });
  await page.addInitScript(() => { localStorage.setItem('sifas_lang', 'ko'); Object.defineProperty(window, 'ViewerRig', {configurable: true, set(api) { const create = api.create;
   api.create = function () { const rig = create.apply(this, arguments); window.__gazeRoot = arguments[0]; window.__gazeRig = rig; return rig; }; Object.defineProperty(window, 'ViewerRig', {configurable: true, writable: true, value: api}); }}); });
  await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === 'function');
  await page.evaluate(() => { const Original = THREE.OrbitControls; THREE.OrbitControls = function (camera, canvas) {
    const controls = new Original(camera, canvas); window.__gazeCamera = camera; window.__gazeControls = controls; return controls;
  }; THREE.OrbitControls.prototype = Original.prototype; });
  await page.evaluate(paths => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer(paths); }, [path.join(source, 'ayumu-body.unity'), path.join(source, 'ayumu-face.unity')]);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading);
  await (await show(page.locator('#viewer-game-motions'))).click();
  await page.waitForFunction(() => Array.from(document.getElementById('viewer-motion-character').options).some(option => option.value === '201'));
  await page.locator('#viewer-motion-character').selectOption('201'); await page.locator('#viewer-motion-category').selectOption('mv');
  await page.waitForFunction(() => !document.getElementById('viewer-motion-song-type').parentElement.hidden);
  await page.locator('#viewer-motion-song-type').selectOption('solo');
  await page.waitForFunction(() => Array.from(document.getElementById('viewer-game-motion-choice').options).some(option => option.value === 'mv:12002:1200201'));
  await page.locator('#viewer-game-motion-choice').selectOption('mv:12002:1200201'); await page.locator('#viewer-motion-performer').selectOption('1');
  await page.locator('#viewer-motion-linked-audio').uncheck(); await page.locator('#viewer-motion-import').click();
  await page.waitForFunction(() => !document.getElementById('viewer-game-motions-dialog').open && !ModelViewer.getState().loading && ModelViewer.getState().rig.selectedClip.startsWith('game-timeline:mv:'));
  assert(prepared && prepared.rig.motionTimelines.length, 'Backend verifies the original composite receipt');
  const descriptor = prepared.rig.motionTimelines.find(entry => entry.category === 'mv'); assert(descriptor);
  await page.evaluate(descriptor => ModelViewer.setMotionTimeline(descriptor), descriptor);
  await page.waitForFunction(() => ModelViewer.getState().rig.selectedClip.startsWith('game-timeline:mv:'));
  const cameraEvent = descriptor.facial.events.find(event => event.kind === 'gaze' && event.target === 21);
  const time = cameraEvent.start + cameraEvent.duration * .4;
  async function snapshot() { return page.evaluate(() => { const s = ModelViewer.getState(); return {clip:s.rig.selectedClip,time:s.rig.time,gaze:s.rig.motionGaze,expression:s.rig.expressionPanel,
    eyes:s.rig.bones.filter(bone => /(?:^|\/)(Left|Right)Eye[12]$/.test(bone.name)),morphs:s.rig.expressions,physics:s.rig.physics,probe:ModelViewer.renderProbe(33)}; }); }
  await page.locator('#viewer-time').evaluate((node, time) => { node.value = String(time); node.dispatchEvent(new Event('input', {bubbles:true})); }, time);
  const authored = await snapshot(); assert(authored.gaze.available && Object.values(authored.gaze.weights).some(value => value > .001), 'Actual Camera21 source event samples original eye poses');
  report.authored = authored;
  assert.equal(authored.expression.gaze.mode, 'motion'); assert(authored.eyes.length >= 4);
  const beforeCamera = JSON.stringify(authored.eyes);
  await (await show(page.locator('[data-viewer-view=left]'))).click(); await page.waitForTimeout(150);
  const left = await snapshot(); assert.notEqual(JSON.stringify(left.eyes), beforeCamera, 'Original gaze reacts to changed preview camera while paused'); assert.equal(left.time, authored.time);
  const mode = await show(page.locator('#viewer-gaze-mode')); await mode.selectOption('front'); const neutral = await snapshot();
  assert.notEqual(JSON.stringify(neutral.eyes), JSON.stringify(left.eyes), 'Explicit front gaze restores original neutral iris positions');
  assert.deepStrictEqual(neutral.morphs, left.morphs, 'Manual gaze leaves all eyelid/mouth weights unchanged');
  await mode.selectOption('direction'); await page.locator('#viewer-gaze-horizontal-number').fill('40'); await page.locator('#viewer-gaze-horizontal-number').dispatchEvent('input');
  await page.locator('#viewer-gaze-vertical-number').fill('30'); await page.locator('#viewer-gaze-vertical-number').dispatchEvent('input');
  const manual = await snapshot(); assert.equal(manual.expression.gaze.horizontal, .4); assert.equal(manual.expression.gaze.vertical, .3);
  assert.notEqual(JSON.stringify(manual.eyes), JSON.stringify(neutral.eyes)); assert.deepStrictEqual(manual.morphs, neutral.morphs);
  await page.evaluate(state => window.__gazeRig.restoreInspectionState(state, {strict:true}), await page.evaluate(() => ModelViewer.getState().rig));
  const restored = await snapshot(); assert.deepStrictEqual(restored.expression.gaze, manual.expression.gaze, 'Inspection/Undo restores precise gaze controls and poses');
  // Move the real renderer camera in the animated face's local axes. Observe
  // the actual weighted original iris vertices, not only a nonzero UI value.
  const axisSamples = await page.evaluate(() => {
    const root = window.__gazeRoot, camera = window.__gazeCamera, controls = window.__gazeControls, rig = window.__gazeRig;
    let face; root.traverse(node => { if ((node.userData.originalName || node.name) === 'Eye_Root') face = node; });
    if (!face) throw Error('Actual original face reference unavailable');
    const q = new THREE.Quaternion(), chain = []; for(let n = face; n; n = n.parent) chain.push(n); for(let i = chain.length - 1; i >= 0; i--) q.multiply(chain[i].quaternion);
    const origin = face.getWorldPosition(new THREE.Vector3()), inverse = q.clone().invert();
    function centroid() {
      root.updateMatrixWorld(true); const sum = new THREE.Vector3(); let count = 0;
      root.traverse(mesh => {
        if (!mesh.isSkinnedMesh || (mesh.userData.originalName || mesh.name).replace(/__\d+$/, '') !== 'Eye') return;
        mesh.skeleton.update(); const a = mesh.geometry.attributes;
        for(let i = 0; i < a.position.count; i++) {
          let weight = 0; for(let k = 0; k < 4; k++) { const bone = mesh.skeleton.bones[a.skinIndex.getComponent ? a.skinIndex.getComponent(i,k) : a.skinIndex.array[i*4+k]];
            if(bone && /^(Left|Right)Eye[12](?:__\d+)?$/.test(bone.userData.originalName || bone.name)) weight += a.skinWeight.array[i*4+k]; }
          if(weight < .5) continue;
          const point = new THREE.Vector3().fromBufferAttribute(a.position,i); mesh.boneTransform(i,point); point.applyMatrix4(mesh.matrixWorld).sub(origin).applyQuaternion(inverse);
          sum.add(point); count++;
        }
      });
      if(!count) throw Error('Actual weighted iris vertices unavailable'); return {count, position:sum.divideScalar(count).toArray()};
    }
    const mode = document.getElementById('viewer-gaze-mode'); mode.value='front'; mode.dispatchEvent(new Event('change',{bubbles:true})); const neutral = centroid(), samples=[];
    for(const [axis,sign] of [[0,1],[0,-1],[1,1],[1,-1]]) {
      const offset = new THREE.Vector3(0,0,2); offset.setComponent(axis,.7*sign); camera.position.copy(origin).add(offset.applyQuaternion(q)); controls.target.copy(origin); controls.update();
      mode.value='camera'; mode.dispatchEvent(new Event('change',{bubbles:true})); rig.refreshGaze();
      samples.push({axis,sign,camera:camera.position.toArray(),vertices:centroid(),weights:rig.getState().expressionPanel.gaze.weights});
    }
    return {neutral,samples};
  });
  report.axisSamples = axisSamples;
  for(const sample of axisSamples.samples) assert((sample.vertices.position[sample.axis] - axisSamples.neutral.position[sample.axis]) * sample.sign > 1e-6, 'Actual original iris vertices move toward camera +/-X and +/-Y');
  await (await show(page.locator('[data-viewer-view=front]'))).click(); await (await show(page.locator('#viewer-fit'))).click();
  await (await show(page.locator('#viewer-gaze-reset'))).click(); await page.waitForFunction(() => ModelViewer.renderProbe(33).nonBackgroundSamples > 0);
  const reset = await snapshot(); report.reset = reset; assert.equal(reset.expression.gaze.mode, 'motion');
  assert.deepStrictEqual(reset.morphs, authored.morphs); assert(reset.probe.ready && reset.probe.glError === 0 && reset.probe.nonBackgroundSamples > 0);
  const missing = descriptor.facial.events.find(event => event.kind === 'gaze' && event.target === 22); assert(missing);
  await page.locator('#viewer-time').evaluate((node, time) => { node.value = String(time); node.dispatchEvent(new Event('input', {bubbles:true})); }, missing.start + missing.duration * .5);
  const audience = await snapshot(); assert(audience.gaze.missingTargets.includes(22), 'An unavailable original audience target is reported instead of guessed');
  await (await show(page.locator('#viewer-game-motions'))).click();
  await page.locator('#viewer-motion-category').selectOption('voice');
  await page.waitForFunction(() => Array.from(document.getElementById('viewer-motion-character').options).some(option => option.value === '1'));
  await page.locator('#viewer-motion-character').selectOption('1'); await page.locator('#viewer-motion-search').fill('voice:1001014');
  await page.waitForFunction(() => Array.from(document.getElementById('viewer-game-motion-choice').options).some(option => option.value === 'voice:1001014'));
  await page.locator('#viewer-game-motion-choice').selectOption('voice:1001014'); await page.locator('#viewer-motion-import').click();
  await page.waitForFunction(() => !document.getElementById('viewer-game-motions-dialog').open && !ModelViewer.getState().loading && ModelViewer.getState().rig.selectedClip === 'game-timeline:voice:voice:1001014:1');
  assert.equal(prepared.rig.expressionCatalog.gaze.owner, 201);
  assert(prepared.rig.expressionCatalog.gaze.clips.every(clip => clip.sourceName.startsWith('ch0201_')), 'Mixed original0201/0001 banks prefer displayed face201 endpoints');
  const mixed = await snapshot(); report.mixed = mixed;
  assert(mixed.gaze.retargeted && mixed.gaze.sourceOwner === 201, 'Retained/imported character1 gaze uses current201 original iris endpoints');
  await (await show(page.locator('#viewer-expression-gaze'))).screenshot({path: path.join(evidence, 'gaze-controls.png')});
  report.status = 'PASS'; Object.assign(report, {preparedSources:prepared.source_names, authored,left,neutral,manual,restored,reset,audience,errors}); assert.deepStrictEqual(errors, []);
 } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
 finally { fs.writeFileSync(path.join(evidence,'report.json'), JSON.stringify(report,null,2)); if(browser) await browser.close(); if(server) server.kill('SIGTERM'); console.log(JSON.stringify({status:report.status,evidence,error:report.error})); }
}
main();
