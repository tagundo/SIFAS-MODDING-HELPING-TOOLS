/* MV Studio follow camera in the real workbench (Korean UI).

   Synthetic game project (stage fixture model; one performer built from the same fixture, whose
   Head bone (node 6) is its follow target and whose Move bone (node 1) stands in for the hips; a
   MainCamera AnimationTrack with two dense 60 Hz shots whose editableValues include keyframes;
   not a native timeline, so it saves without a source bundle):
   - no regression: the opened project stays deep-equal to its input, with no editor layer;
   - the Follow camera panel open while an import runs, and while the saved project is opened
     again: every control in it is enabled once the import ends;
   - Camera tab: the rig lane "카메라 리그 (편집기)" is listed after the MainCamera track;
   - Add follow camera → a rig clip on that lane covering the shot at the playhead, and mid-rig the
     game camera aims at the head (< 0.5°) from the set distance (front view, audience side);
   - moving the performer (Performers → X) rebakes and the camera follows; the Back view preset
     puts the camera behind the member;
   - a slider drag is one undo step;
   - the rig is extended over the second shot, then its end edge is dragged back on the lane (one
     undo step): the shot outside it gets its original samples back;
   - random scrubbing gives the same pose as playing to the same time;
   - Ctrl+Z restores the longer rig;
   - save → reopen keeps the rig and the baked samples;
   - every follow camera string has Korean and Japanese copy, and the panel follows a language switch.

   Korean screenshots (the panel, and the rig on the Camera tab) go to EVIDENCE_DIR (a temporary
   folder otherwise). */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-follow-library-'));
const modded = path.join(library, 'modded');
const ownEvidence = !process.env.EVIDENCE_DIR;
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-follow-browser-'));
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, 'stage-fixture.glb'), fixture().glb);

async function startServer() {
  const socket = net.createServer();
  await new Promise((resolve) => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  const processLog = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const processHandle = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)], {
    cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', processLog, processLog],
  });
  fs.closeSync(processLog);
  const url = 'http://127.0.0.1:' + port;
  for (let count = 0; count < 100; count++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { processHandle, url }; } catch (_) {}
    if (processHandle.exitCode !== null) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  processHandle.kill();
  throw new Error('Isolated workbench did not start');
}

// A shot orbiting the stage centre, looking at it (Unity rig space: the rig looks along -Z).
function shotSamples(count, from, to) {
  const frames = [];
  for (let index = 0; index < count; index++) {
    const s = index / (count - 1), angle = (from + (to - from) * s) * Math.PI / 180, radius = 5 - s;
    const position = [radius * Math.sin(angle), 1.4 + .3 * s, radius * Math.cos(angle)];
    const pan = Math.atan2(position[0], position[2]) * 180 / Math.PI;
    const tilt = -8, half = (degrees) => degrees * Math.PI / 360;
    const [sy, cy, sx, cx] = [Math.sin(half(pan)), Math.cos(half(pan)), Math.sin(half(tilt)), Math.cos(half(tilt))];
    frames.push({ time: index / 60, position, rotation: [cy * sx, sy * cx, -sy * sx, cy * cx], fov: 30 + 4 * s });
  }
  return frames;
}

function gameProject(local) {
  const shot = (id, start, count, from, to) => ({ id, start, duration: (count - 1) / 60, label: `${Math.round(start * 60)}_${Math.round(start * 60) + count - 1}`,
    values: { clipIn: 0, timeScale: 1, preExtrapolationMode: 1, postExtrapolationMode: 1, preExtrapolationTime: 0, postExtrapolationTime: 1 / 60,
      playableClass: 'AnimationPlayableAsset', m_Position: { x: 0, y: 0, z: 0 }, m_Rotation: { x: 0, y: 0, z: 0, w: 1 },
      keyframes: shotSamples(count, from, to) },
    editableValues: ['clipIn', 'timeScale', 'preExtrapolationMode', 'postExtrapolationMode', 'preExtrapolationTime', 'postExtrapolationTime', 'keyframes'] });
  return {
    version: 1, name: 'Follow camera MV', duration: 12, nativeTimeline: false, assets: local.assets, stage: local.stage, warnings: [], quality: {},
    performers: [{ id: 'actor-1', label: 'Actor 1', position: 1, glb: local.stage.glb, transform: { position: [0, 0, 0] },
      rig: { focusParts: { 0: 6, 3: 1 } } }],
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 78, assetId: 1 },
    tracks: [
      { id: 'cam', kind: 'camera', label: 'CameraMotion/Camera1', nativeClass: 'AnimationTrack', binding: '/EntryPoint/Live/Cameras/MainCamera',
        events: [shot('cam:0', 0, 241, -30, 10), shot('cam:1', 241 / 60, 301, 20, 50)] },
      { id: 'light', kind: 'lighting', label: 'StageEffect/BaseLight', nativeClass: 'LiveBaseLightTrack',
        events: [{ id: 'light:0', start: 0, duration: 9, values: { playableClass: 'LiveBaseLightClip' } }] },
    ],
  };
}

async function importGame(page, project) {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
    regions: [{ id: 'gl', label: 'GL' }], platforms: [{ id: 'android', label: 'Android' }],
    songs: [{ id: 78, title: project.name, variants: [{ id: 1, label: 'MV' }] }] } }));
  await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: project }));
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
  await page.locator('#mv-game-load').click();
  await page.waitForFunction((name) => MVStudio.getState().project?.name === name && !document.getElementById('mv-import-game').disabled, project.name);
}

const state = (page) => page.evaluate(() => MVStudio.getState());
const seek = (page, time) => page.evaluate((value) => { window.probeCtx.seek(value, { audio: false }); return window.probeCtx.time(); }, time);
const camera = (page) => page.evaluate(() => window.probeCtx.scene().inspect().camera);
// The bake (and any member sampling) is done.
const settle = (page) => page.evaluate(async () => {
  for (let index = 0; index < 400; index++) {
    await MVStudioCameraKeys.pending(window.probeCtx);
    const follow = MVStudioCameraFollow.state(window.probeCtx);
    if (!follow.dirty && !follow.progress) return follow;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error('The follow camera bake did not finish');
});
const angleBetween = (a, b) => {
  const dot = Math.abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]);
  const cross = [a[3] * b[0] - a[0] * b[3] - a[1] * b[2] + a[2] * b[1], a[3] * b[1] - a[1] * b[3] - a[2] * b[0] + a[0] * b[2],
    a[3] * b[2] - a[2] * b[3] - a[0] * b[1] + a[1] * b[0]];
  return 2 * Math.atan2(Math.hypot(...cross), dot) * 180 / Math.PI;
};
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const near = (actual, expected, tolerance, message) => assert(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} != ${expected}`);
// Degrees between the camera's view (-Z) and the direction to `point` (three space).
const aimError = (page, point) => page.evaluate((target) => {
  const view = window.probeCtx.scene().inspect().camera;
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(new THREE.Quaternion(...view.quaternion));
  const toward = new THREE.Vector3(...target).sub(new THREE.Vector3(...view.position));
  return { degrees: forward.angleTo(toward) * 180 / Math.PI, distance: toward.length(), position: view.position, fov: view.authoredFov };
}, point);

// Every control of the open Follow camera panel becomes enabled once the editor is unlocked (the
// host re-renders only its own panels then). Returns the number of controls.
async function panelEnabled(page, message) {
  await page.waitForFunction(() => !window.probeCtx.locked());
  const result = await page.waitForFunction(() => {
    const panel = document.getElementById('mv-panel-follow');
    const controls = panel && panel.open && !panel.hidden ? [...panel.querySelectorAll('input, select, button')] : [];
    return controls.length && controls.every((node) => !node.disabled) ? controls.length : 0;
  }, null, { timeout: 3000 }).catch(async () => {
    const disabled = await page.evaluate(() => [...document.querySelectorAll('#mv-panel-follow input, #mv-panel-follow select, #mv-panel-follow button')]
      .filter((node) => node.disabled).map((node) => node.id || node.dataset.mvFollow || node.dataset.mvFollowView || node.tagName));
    assert.fail(`${message}: ${disabled.length} panel controls stay disabled ${JSON.stringify(disabled.slice(0, 8))}`);
  });
  return result.jsonValue();
}

async function newPage(browser, errors) {
  const page = await browser.newPage({ locale: 'ko', viewport: { width: 1400, height: 1000 } });
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => dialog.accept());
  await page.addInitScript(() => {
    (window.MVStudioPlugins ||= []).push({ id: 'test-probe', order: 99, attach(ctx) { window.probeCtx = ctx; } });
  });
  return page;
}

async function synthetic(browser, url) {
  const errors = [];
  const page = await newPage(browser, errors);
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
  assert(local.stage && local.stage.glb, 'the stage fixture opens');
  const project = gameProject(local);
  // The Follow camera panel is open while the import runs (a remembered open panel): it is built
  // while the editor is still locked, and its controls must be enabled once the import ends.
  await page.evaluate(() => { document.getElementById('mv-panel-follow').open = true; });
  await importGame(page, project);
  await panelEnabled(page, 'after an import that ran with the panel open');
  await page.locator('#mv-camera-mode').waitFor();
  await page.waitForFunction(() => window.probeCtx.scene()?.memberTargets?.().some((member) => member.slot === 1));

  // No regression: nothing is written on load.
  let current = await state(page);
  assert.deepEqual(current.project, project, 'the opened project is unchanged');
  assert.equal(current.project.editor, undefined, 'no editor layer before an edit');
  assert.deepEqual(await page.evaluate(() => window.probeCtx.scene().memberTargets()), [{ slot: 1, id: 'actor-1', parts: [0, 3], facing: true }]);

  // Camera tab: no rig lane before the first rig.
  await page.locator('#mv-tab-camera').click();
  const laneLabel = page.locator('.mv-lane-extra-label', { hasText: '카메라 리그 (편집기)' });
  const lanes = () => page.evaluate(() => [...document.querySelectorAll('#mv-timeline-grid > .mv-lane')].map((lane) => lane.dataset.track || lane.dataset.extra));
  assert.deepEqual(await lanes(), ['cam'], 'only the camera track before a rig exists');

  // The panel: Korean, with the add button and its explanation.
  assert.equal(await page.locator('#mv-panel-follow > summary').textContent(), '따라가기 카메라');
  assert.equal(await page.evaluate(() => document.getElementById('mv-panel-follow').open), true, 'the panel stayed open');
  assert.equal(await page.locator('#mv-follow-add').textContent(), '따라가기 카메라 추가');
  assert.match(await page.locator('#mv-follow-empty').textContent(), /Cinemachine/);

  // Add follow camera at 1.0 s: the rig covers shot 0.
  await seek(page, 1);
  await page.locator('#mv-follow-add').click();
  await settle(page);
  current = await state(page);
  const rigs = current.project.editor.camera.rigs;
  assert.equal(rigs.length, 1);
  assert.equal(rigs[0].start, 0);
  near(rigs[0].end, 4, 1e-9, 'covers the shot at the playhead');
  assert.deepEqual(rigs[0].target, { slot: 1, part: 0 });
  assert.equal(current.history.undoLabel, 'Add follow camera');
  assert.equal(current.project.editor.camera.shots, undefined, 'no camera key record is written');
  assert.equal(await laneLabel.count(), 1, 'the rig lane is listed');
  assert.deepEqual(await lanes(), ['cam', 'camera-rigs'], 'right after the MainCamera track');
  const clip = page.locator('.mv-lane-extra[data-extra="camera-rigs"] .mv-rig-clip');
  assert.equal(await clip.count(), 1, 'the rig clip on the Camera tab');
  assert.equal(await clip.getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#mv-follow-name').inputValue(), '따라가기 카메라 1');
  assert.equal(await page.locator('[data-mv-follow-view="front"]').getAttribute('aria-pressed'), 'true');
  assert.deepEqual(await page.locator('[data-mv-follow-view]').allTextContents(), ['정면', '후면', '왼쪽', '오른쪽', '사용자']);
  for (const text of ['데드존', '높이 고정', '댐핑']) assert.equal(await page.locator('.mv-follow-section legend', { hasText: text }).count(), 1, text);
  assert.match(await page.locator('.mv-follow-section', { hasText: '데드존' }).locator('.mv-follow-help').textContent(), /무시합니다/);
  assert.match(await page.locator('#mv-follow-notice').textContent(), /높이 고정: 카메라/);

  // Mid-rig the game camera aims at the head from 2.5 m on the audience side.
  const head = [0, 1.5, 0];
  for (const time of [1, 2, 3.4]) {
    await seek(page, time);
    const aim = await aimError(page, head);
    assert(aim.degrees < .5, `t=${time}: aims at the head (${aim.degrees}°)`);
    near(aim.distance, 2.5, 1e-3, `t=${time}: at the rig distance`);
    assert(aim.position[2] > 2.4, 'front view: the audience side (+Z)');
    near(aim.fov, 30, 1e-6, 'the rig FOV');
  }
  const baked0 = (await state(page)).project.tracks[0].events[0].values.keyframes;
  assert.notDeepEqual(baked0, project.tracks[0].events[0].values.keyframes, 'shot 0 baked');
  assert.deepEqual((await state(page)).project.tracks[0].events[1].values.keyframes, project.tracks[0].events[1].values.keyframes, 'shot 1 untouched');
  await page.screenshot({ path: path.join(evidence, 'follow-rig-camera-tab-ko.png') });

  // Moving the performer rebakes: the camera follows.
  await page.locator('#mv-performers summary').click();
  const axis = page.locator('[data-mv-performer-axis=X]');
  await axis.fill('1');
  await axis.press('Tab');
  await page.locator('#mv-performers summary').click();
  await settle(page);
  await seek(page, 2);
  let aim = await aimError(page, [1, 1.5, 0]);
  assert(aim.degrees < .5, `after the performer move the camera aims at the head (${aim.degrees}°)`);
  near(aim.position[0], 1, 1e-3, 'and stands in front of it');

  // The Back view preset: behind the member.
  await page.locator('[data-mv-follow-view="back"]').click();
  await settle(page);
  await seek(page, 2);
  aim = await aimError(page, [1, 1.5, 0]);
  assert(aim.degrees < .5 && aim.position[2] < -2.4, `back view (${aim.degrees}°, z ${aim.position[2]})`);
  assert.equal(await page.locator('[data-mv-follow-view="back"]').getAttribute('aria-pressed'), 'true');
  await page.locator('[data-mv-follow-view="front"]').click();
  await settle(page);

  // Bake progress with Cancel (the member sampler held at 40 %), then Bake again.
  await page.evaluate(() => {
    const scene = window.probeCtx.scene(), sample = scene.sampleMemberPath;
    window.restoreSampler = () => { scene.sampleMemberPath = sample; };
    scene.sampleMemberPath = async (options) => {
      options.onProgress?.(Math.floor(options.times.length * .4), options.times.length);
      await new Promise((resolve) => { window.releaseSampler = resolve; options.signal?.addEventListener('abort', resolve, { once: true }); });
      if (options.signal?.aborted) throw new DOMException('cancelled', 'AbortError');
      return sample(options);
    };
  });
  const beforeMove = (await state(page)).project.tracks[0].events[0].values.keyframes;
  await page.locator('#mv-performers summary').click();
  await axis.fill('2');
  await axis.press('Tab');
  await page.locator('#mv-performers summary').click();
  await page.locator('#mv-follow-progress').waitFor();
  const percent = Number(/^카메라 굽는 중… (\d+)%/.exec(await page.locator('#mv-follow-progress').textContent())?.[1]);
  assert(percent >= 35 && percent <= 40, `the progress line (${percent} %)`);
  await page.locator('#mv-panel-follow').scrollIntoViewIfNeeded();
  await page.locator('#mv-follow-status').screenshot({ path: path.join(evidence, 'follow-progress-ko.png') });
  await page.locator('#mv-follow-cancel').click();
  await page.locator('#mv-follow-rebake').waitFor();
  assert.match(await page.locator('#mv-follow-cancelled').textContent(), /굽기를 취소했습니다/);
  assert.equal(await page.locator('#mv-follow-rebake').textContent(), '다시 굽기');
  assert.deepEqual((await state(page)).project.tracks[0].events[0].values.keyframes, beforeMove, 'a cancelled bake keeps the samples');
  await page.evaluate(() => window.restoreSampler());
  await page.locator('#mv-follow-rebake').click();
  await settle(page);
  await seek(page, 2);
  aim = await aimError(page, [2, 1.5, 0]);
  assert(aim.degrees < .5 && Math.abs(aim.position[0] - 2) < 1e-3, `Bake again follows the moved member (${aim.degrees}°)`);
  await page.locator('#mv-performers summary').click();
  await axis.fill('1');
  await axis.press('Tab');
  await page.locator('#mv-performers summary').click();
  await settle(page);

  // A slider drag is one undo step.
  const undoBefore = (await state(page)).history.undo;
  const slider = page.locator('[data-mv-follow-range="distance"]');
  await slider.scrollIntoViewIfNeeded();
  const box = await slider.boundingBox();
  await page.mouse.move(box.x + box.width * .15, box.y + box.height / 2);
  await page.mouse.down();
  for (const fraction of [.2, .25, .3]) await page.mouse.move(box.x + box.width * fraction, box.y + box.height / 2, { steps: 3 });
  await page.mouse.up();
  await settle(page);
  current = await state(page);
  assert.equal(current.history.undo, undoBefore + 1, 'one undo step for the drag');
  assert.equal(current.history.undoLabel, 'Edit follow camera');
  const dragged = current.project.editor.camera.rigs[0].distance;
  assert(dragged > 2.5 && dragged < 6, `distance dragged (${dragged})`);
  near(Number(await page.locator('[data-mv-follow="distance"]').inputValue()), dragged, 1e-3, 'the number box follows');
  await seek(page, 2);
  aim = await aimError(page, [1, 1.5, 0]);
  near(aim.distance, dragged, 1e-3, 'the camera at the dragged distance');
  const distanceBox = page.locator('[data-mv-follow="distance"]');
  await distanceBox.fill('2.5');
  await distanceBox.press('Tab');
  await settle(page);

  // Extend the rig over shot 1, then drag its end edge back on the lane: shot 1 is its original again.
  const endBox = page.locator('[data-mv-follow="end"]');
  await endBox.fill('6');
  await endBox.press('Tab');
  await settle(page);
  current = await state(page);
  assert.equal(current.project.editor.camera.rigs[0].end, 6);
  assert.notDeepEqual(current.project.tracks[0].events[1].values.keyframes, project.tracks[0].events[1].values.keyframes, 'shot 1 follows too');
  await page.locator('#mv-zoom').selectOption('48');
  await seek(page, 9);
  const rigClip = page.locator('.mv-rig-clip');
  await rigClip.scrollIntoViewIfNeeded();
  const rigBox = await rigClip.boundingBox();
  const undoDrag = (await state(page)).history.undo;
  await page.mouse.move(rigBox.x + rigBox.width - 2, rigBox.y + rigBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(rigBox.x + rigBox.width - 60, rigBox.y + rigBox.height / 2, { steps: 4 });
  await page.mouse.move(rigBox.x + rigBox.width - 3.2 * 48, rigBox.y + rigBox.height / 2, { steps: 4 });
  await page.mouse.up();
  await settle(page);
  current = await state(page);
  const end = current.project.editor.camera.rigs[0].end;
  assert(end < 241 / 60 && end > 2, `the end edge was dragged back (${end})`);
  near(end * 60, Math.round(end * 60), 1e-9, 'frame-snapped');
  assert.equal(current.history.undo, undoDrag + 1, 'one undo step for the drag');
  assert.equal(current.history.undoLabel, 'Resize follow camera');
  assert.deepEqual(current.project.tracks[0].events[1].values.keyframes, project.tracks[0].events[1].values.keyframes, 'shot 1 has its original samples back');
  const after = Math.ceil(end * 60) + 1;
  assert.deepEqual(current.project.tracks[0].events[0].values.keyframes.slice(after), project.tracks[0].events[0].values.keyframes.slice(after),
    'shot 0 after the rig: original samples');

  // Keyboard: Alt+→ nudges the focused rig one frame, Ctrl+Z puts it back; the rig keeps the focus.
  const focusedRig = () => page.evaluate(() => document.activeElement?.classList.contains('mv-rig-clip') ? document.activeElement.dataset.rig : null);
  const rigId = current.project.editor.camera.rigs[0].id;
  await page.locator('.mv-rig-clip').focus();
  await page.keyboard.press('Alt+ArrowRight');
  await settle(page);
  current = await state(page);
  near(current.project.editor.camera.rigs[0].start, 1 / 60, 1e-9, 'Alt+→ moves the rig one frame');
  assert.equal(current.history.undoLabel, 'Move follow camera');
  assert.equal(await focusedRig(), rigId, 'the rig keeps the focus after a nudge');
  await page.keyboard.press('Control+z');
  await settle(page);
  assert.equal((await state(page)).project.editor.camera.rigs[0].start, 0, 'Ctrl+Z on the rig');
  assert.equal(await focusedRig(), rigId, 'and after Ctrl+Z');

  // Scrubbing in any order gives the pose playing reached at the same time.
  await seek(page, .3);
  await page.locator('#mv-play').click();
  const played = await page.evaluate(() => new Promise((resolve) => {
    const list = [];
    const step = () => {
      const view = window.probeCtx.scene().inspect();
      if (view.time > .3 && view.time < 1.9) list.push({ time: view.time, position: view.camera.position, quaternion: view.camera.quaternion });
      if (view.time >= 1.9 || list.length > 300) resolve(list); else requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }));
  await page.locator('#mv-play').click();
  assert(played.length >= 10, `sampled playback (${played.length} frames)`);
  const order2 = played.map((item, index) => [Math.sin(index * 12.9898) * 43758.5453 % 1, item]).sort((a, b) => a[0] - b[0]).map((pair) => pair[1]);
  for (const sample of order2) {
    await seek(page, sample.time);
    const view = await camera(page);
    assert(distance(view.position, sample.position) < 1e-6 && angleBetween(view.quaternion, sample.quaternion) < 1e-4,
      `t=${sample.time.toFixed(4)}: scrub = play`);
  }

  // Ctrl+Z restores the longer rig and shot 1 follows again.
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  await settle(page);
  current = await state(page);
  assert.equal(current.project.editor.camera.rigs[0].end, 6, 'undo');
  assert.notDeepEqual(current.project.tracks[0].events[1].values.keyframes, project.tracks[0].events[1].values.keyframes);

  // Screenshots: the whole panel in a tall window.
  await page.setViewportSize({ width: 1400, height: 2400 });
  await page.waitForTimeout(200);
  await page.locator('#mv-panel-follow').scrollIntoViewIfNeeded();
  await page.locator('#mv-panel-follow').screenshot({ path: path.join(evidence, 'follow-panel-ko.png') });
  await page.setViewportSize({ width: 1400, height: 1000 });
  await seek(page, 2);
  await page.locator('#mv-tab-camera').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(evidence, 'follow-camera-tab-ko.png') });

  // Save → reopen keeps the rig and the baked samples.
  current = await state(page);
  await page.locator('#mv-save').click();
  const link = page.locator('#mv-save-result a');
  await Promise.race([link.waitFor(), page.waitForFunction(() => document.getElementById('mv-status').classList.contains('mv-error'))]);
  assert.equal(await page.locator('#mv-status.mv-error').count(), 0, 'save: ' + await page.locator('#mv-status').textContent());
  const restored = await page.request.post(url + '/api/mv-studio/open', { data: { path: await link.getAttribute('title') } }).then((reply) => reply.json());
  assert.deepEqual(restored.editor.camera.rigs, current.project.editor.camera.rigs, 'rigs saved');
  for (const index of [0, 1]) {
    assert.deepEqual(restored.tracks[0].events[index].values.keyframes, current.project.tracks[0].events[index].values.keyframes, `shot ${index} baked samples saved`);
  }

  // Every string has Korean and Japanese copy; the panel follows a language switch.
  const strings = await page.evaluate(() => MVStudioCameraFollow.STRINGS);
  for (const lang of ['ko', 'ja']) {
    const table = await page.request.get(url + '/api/i18n?lang=' + lang).then((reply) => reply.json());
    assert.deepEqual(strings.filter((text) => !(text in table.strings)), [], `${lang} copy for every follow camera string`);
  }
  await page.locator('#lang-select').selectOption('en');
  await page.waitForFunction(() => document.querySelector('#mv-panel-follow > summary')?.textContent === 'Follow camera');
  await page.waitForFunction(() => document.getElementById('mv-follow-add')?.textContent === 'Add follow camera');
  assert.deepEqual(await page.locator('[data-mv-follow-view]').allTextContents(), ['Front view', 'Back view', 'Left view', 'Right view', 'Custom view']);
  const japanese = await page.request.get(url + '/api/i18n?lang=ja').then((reply) => reply.json());
  await page.locator('#lang-select').selectOption('ja');
  await page.waitForFunction((text) => document.getElementById('mv-follow-add')?.textContent === text, japanese.strings['Add follow camera']);
  await page.locator('#lang-select').selectOption('ko');
  await page.waitForFunction(() => document.getElementById('mv-follow-add')?.textContent === '따라가기 카메라 추가');

  // Delete the rig: the shots are their originals again.
  await page.locator('#mv-follow-delete').click();
  await settle(page);
  current = await state(page);
  assert.equal(current.project.editor.camera.rigs, undefined);
  for (const index of [0, 1]) assert.deepEqual(current.project.tracks[0].events[index].values.keyframes, project.tracks[0].events[index].values.keyframes);
  assert.equal(await page.locator('.mv-rig-clip').count(), 0);
  assert.deepEqual(await lanes(), ['cam'], 'the rig lane leaves with the last rig');

  // Reopening the saved project (with its rig) while the panel is open: the rig controls are enabled.
  await importGame(page, { ...restored, name: 'Follow camera MV (reopened)' });
  const controls = await panelEnabled(page, 'after reopening a project with a rig, the panel open');
  assert(controls > 20, `the rig controls are shown (${controls})`);
  assert.equal(await page.locator('#mv-follow-name').inputValue(), '따라가기 카메라 1');
  assert.deepEqual(errors, []);
  await page.close();
}

async function run() {
  let browser, server;
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    await synthetic(browser, server.url);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    if (server) server.processHandle.kill();
    fs.rmSync(library, { recursive: true, force: true });
    if (ownEvidence && process.exitCode === undefined) fs.rmSync(evidence, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
