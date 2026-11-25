/* MV Studio camera editor in the real workbench (Korean UI).

   Synthetic game project (stage fixture model, a MainCamera AnimationTrack with two
   dense 60 Hz shots whose editableValues include keyframes; not a native timeline, so
   it can be saved without its source bundle):
   - no regression: the opened project stays deep-equal to its input, with no editor;
   - the dense sample editor is replaced by a summary that opens the camera editor;
   - the snap-back fix: Dolly +1 at the shot start moves the camera by 1 m along its
     view at later times, at rest and while the whole shot plays;
   - a key diamond appears on the camera lane and drags frame-snapped;
   - Free camera → orbit → Key current view (K) → back in Game camera the pose equals
     the view (≤ 1e-3 m / 0.01°, same FOV); Ctrl+Z restores, Ctrl+Shift+Z redoes;
   - a clicked or Enter-activated key diamond keeps the focus, so Alt+Arrow moves the key;
   - the curve view renders, and a click on its grid lines seeks; the selected key's time
     is on the header's shot-local clock;
   - a closed panel opened at another shot shows that shot;
   - save → reopen keeps editor.camera and the baked samples;
   - every camera editor string has Korean and Japanese copy, and the whole panel follows a
     language switch (en, ja, back to ko).

   Real 12035 timeline (skipped unless ELICHIKA_STUDIO_TIMELINE_DIR holds
   a-1203503-live_timeline.unity; no game data in Git): an unedited project exports the
   original bytes, and the export of an edited shot re-parses to the baked samples.

   Screenshots go to EVIDENCE_DIR (a temporary folder otherwise). */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-camera-library-'));
const modded = path.join(library, 'modded');
const ownEvidence = !process.env.EVIDENCE_DIR;
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-camera-browser-'));
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, 'stage-fixture.glb'), fixture().glb);
const samples = process.env.ELICHIKA_STUDIO_TIMELINE_DIR || '';
const realTimeline = samples && path.join(samples, 'a-1203503-live_timeline.unity');

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
    const pan = Math.atan2(position[0], position[2]) * 180 / Math.PI;   // -sin(pan) = -x/r, -cos(pan) = -z/r
    const tilt = -8, half = (degrees) => degrees * Math.PI / 360;
    // q = qY(pan) * qX(tilt)
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
    version: 1, name: 'Camera editor MV', duration: 12, nativeTimeline: false, assets: local.assets, stage: local.stage, warnings: [], quality: {},
    performers: [], source: { kind: 'game', region: 'gl', platform: 'android', liveId: 77, assetId: 1 },
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
    songs: [{ id: 77, title: project.name, variants: [{ id: 1, label: 'MV' }] }] } }));
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
const angleBetween = (a, b) => {
  const dot = Math.abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]);
  const cross = [a[3] * b[0] - a[0] * b[3] - a[1] * b[2] + a[2] * b[1], a[3] * b[1] - a[1] * b[3] - a[2] * b[0] + a[0] * b[2],
    a[3] * b[2] - a[2] * b[3] - a[0] * b[1] + a[1] * b[0]];
  return 2 * Math.atan2(Math.hypot(...cross), dot) * 180 / Math.PI;
};
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

async function newPage(browser, errors) {
  const page = await browser.newPage({ locale: 'ko', viewport: { width: 1400, height: 1000 } });
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => dialog.accept());
  // A probe plugin hands the test the editor context (seek, scene) the camera editor gets.
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
  await importGame(page, project);
  await page.locator('#mv-camera-mode').waitFor();

  // No regression: nothing is written on load.
  let current = await state(page);
  assert.deepEqual(current.project, project, 'the opened project is unchanged');
  assert.equal(current.project.editor, undefined, 'no editor layer before an edit');
  assert.equal(await page.locator('#mv-panel-camera').count(), 1, 'the Camera editor panel is listed');
  assert.equal(await page.locator('#mv-panel-camera > summary').textContent(), '카메라 편집기');

  // The dense samples are a summary with a button, not an entry cursor.
  await page.locator('.mv-clip[data-event="cam:0"]').click();
  assert.equal(await page.locator('#mv-event-fields .mv-cam-summary output').textContent(), '샘플 241개 · 60 Hz');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field^="keyframes"]').count(), 0, 'no raw sample fields');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field^="m_Position"]').count(), 0, 'raw playable transforms hidden');
  assert(await page.locator('#mv-panel-camera').evaluate((panel) => panel.open), 'selecting a camera shot opens the camera editor');
  await page.locator('#mv-event-fields .mv-cam-open').click();
  assert.equal(await page.locator('#mv-cam-key-view').textContent(), '현재 시점 키 추가');
  assert.equal(await page.locator('#mv-cam-shot-mode').inputValue(), 'original');

  // Snap-back fix: Dolly +1 at the shot start moves later frames too.
  const times = [.9, 2.1, 3.6];
  const before = [];
  for (const time of times) { await seek(page, time); before.push(await camera(page)); }
  await seek(page, 0);
  if (process.env.CAMERA_DEBUG) console.log(await page.locator('#mv-camera-fields').evaluate((box) => box.outerHTML.slice(0, 3000)));
  const dolly = page.locator('#mv-camera-fields [data-mv-cam="offset.z"]');
  await dolly.fill('1');
  await dolly.press('Tab');
  await page.waitForFunction(() => !!MVStudio.getState().project.editor?.camera?.shots?.['cam:0']);
  current = await state(page);
  assert.deepEqual(current.project.editor.camera.shots['cam:0'].keys.map((key) => [key.frame, key.values.z]), [[0, 1]]);
  assert.equal(current.history.undoLabel, 'Edit camera key');
  for (const [index, time] of times.entries()) {
    await seek(page, time);
    const after = await camera(page);
    const forward = await page.evaluate((q) => new THREE.Vector3(0, 0, -1).applyQuaternion(new THREE.Quaternion(...q)).toArray(), before[index].quaternion);
    const moved = after.position.map((value, axis) => value - before[index].position[axis]);
    assert(distance(moved, forward) < 1e-6, `t=${time}: moved 1 m along the view (${moved})`);
    assert(angleBetween(after.quaternion, before[index].quaternion) < 1e-6, 'same direction');
  }
  assert(await page.locator('.mv-clip[data-event="cam:0"]').evaluate((clip) => clip.classList.contains('mv-edited')), 'the shot is marked edited');

  // Play the whole shot: the offset stays on every frame.
  await seek(page, 0);
  await page.locator('#mv-play').click();
  const played = await page.evaluate(() => new Promise((resolve) => {
    const M = window.MVStudioCameraMath, project = MVStudio.getState().project;
    const original = project.editor.originals['cam:0'].values.keyframes, list = [];
    const step = () => {
      const view = window.probeCtx.scene().inspect();
      if (view.time > .05 && view.time < 3.95) {
        const pose = M.sampleFrames(original, view.time);
        const position = M.unityToThreePosition(pose.position);
        const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(new THREE.Quaternion(...M.unityToThreeQuaternion(pose.rotation)));
        const moved = new THREE.Vector3(...view.camera.position).sub(new THREE.Vector3(...position));
        list.push({ time: view.time, length: moved.length(), along: moved.dot(forward) });
      }
      if (view.time >= 4 || list.length > 400) resolve(list); else requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }));
  await page.locator('#mv-play').click();
  assert(played.length >= 20, `sampled the playing shot (${played.length} frames)`);
  for (const sample of played) {
    assert(Math.abs(sample.length - 1) < 2e-3 && sample.along > .998, `t=${sample.time.toFixed(3)}: still 1 m along the view (${sample.length}, ${sample.along})`);
  }

  // The key diamond on the camera lane: present, then dragged frame-snapped.
  await page.locator('#mv-zoom').selectOption('48');
  const diamond = page.locator('.mv-lane[data-track="cam"] .mv-cam-key[data-event="cam:0"]');
  assert.equal(await diamond.count(), 1);
  assert.equal(await diamond.getAttribute('aria-label'), '키 0:00.00');
  const box = await diamond.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2, { steps: 4 });
  await page.mouse.move(box.x + box.width / 2 + 49, box.y + box.height / 2, { steps: 4 });
  await page.mouse.up();
  current = await state(page);
  const moved = current.project.editor.camera.shots['cam:0'].keys[0].frame;
  assert(Number.isInteger(moved) && Math.abs(moved - 61) <= 2, `dragged about one second, frame-snapped (${moved})`);
  assert.equal(current.history.undoLabel, 'Move camera key');
  near(current.time, moved / 60, 1e-9, 'the playhead follows the key');
  assert.equal(await page.locator(`.mv-lane[data-track="cam"] .mv-cam-key[data-frame="${moved}"]`).getAttribute('aria-pressed'), 'true');
  // The lane refresh replaces the diamonds (and the host would hand the focus to the clip): the
  // key's diamond keeps the focus, after a drag and after Enter, so Alt+Arrow nudges the key.
  const focusedKey = () => page.evaluate(() => {
    const element = document.activeElement;
    return element && element.classList.contains('mv-cam-key') ? Number(element.dataset.frame) : String(element && element.className);
  });
  assert.equal(await focusedKey(), moved, 'the dragged diamond keeps the focus');
  const clipStart = current.project.tracks[0].events[0].start;
  await page.keyboard.press('Enter');
  assert.equal(await focusedKey(), moved, 'Enter selects the key and keeps the focus on its diamond');
  await page.keyboard.press('Alt+ArrowRight');
  current = await state(page);
  assert.equal(current.history.undoLabel, 'Move camera key', 'Alt+Arrow moves the key, not the shot');
  assert.equal(current.project.editor.camera.shots['cam:0'].keys[0].frame, moved + 1);
  assert.equal(current.project.tracks[0].events[0].start, clipStart, 'the shot stays put');
  assert.equal(await focusedKey(), moved + 1, 'the moved diamond has the focus');
  // Ctrl+Z and Ctrl+Shift+Z on the diamond redraw the lane: the key keeps the focus (the moved-back
  // key's diamond takes it), so Alt+Arrow after an undo still moves the key, not the shot.
  const keyFrame = async () => (await state(page)).project.editor.camera.shots['cam:0'].keys[0].frame;
  await page.keyboard.press('Control+z');
  assert.equal(await keyFrame(), moved, 'Ctrl+Z moves the key back');
  assert.equal(await focusedKey(), moved, 'the key diamond keeps the focus after Ctrl+Z');
  await page.keyboard.press('Control+Shift+z');
  assert.equal(await keyFrame(), moved + 1);
  assert.equal(await focusedKey(), moved + 1, 'and after Ctrl+Shift+Z');
  await page.keyboard.press('Control+z');
  await page.keyboard.press('Alt+ArrowRight');
  current = await state(page);
  assert.equal(current.history.undoLabel, 'Move camera key', 'Alt+Arrow after an undo moves the key');
  assert.equal(current.project.editor.camera.shots['cam:0'].keys[0].frame, moved + 1);
  assert.equal(current.project.tracks[0].events[0].start, clipStart, 'the shot stays put');
  assert.equal(await focusedKey(), moved + 1);
  // An undo of the shot's own move (the host redraws the lane first) also leaves the focus on the key.
  await page.locator('.mv-clip[data-event="cam:0"]').focus();
  await page.keyboard.press('Alt+ArrowRight');
  assert.equal((await state(page)).history.undoLabel, 'Move clip');
  await page.locator(`.mv-cam-key[data-event="cam:0"][data-frame="${moved + 1}"]`).focus();
  await page.keyboard.press('Control+z');
  current = await state(page);
  assert.equal(current.project.tracks[0].events[0].start, clipStart, 'Ctrl+Z on the diamond undid the shot move');
  assert.equal(await focusedKey(), moved + 1, 'the key diamond keeps the focus');
  await page.keyboard.press('Alt+ArrowLeft');
  current = await state(page);
  assert.equal(current.history.undoLabel, 'Move camera key');
  assert.equal(current.project.editor.camera.shots['cam:0'].keys[0].frame, moved);
  assert.equal(current.project.tracks[0].events[0].start, clipStart);

  // Free camera → orbit → Key current view (K) → the game camera shows the view.
  const shotStart = 241 / 60, keyTime = shotStart + 75 / 60;
  await seek(page, keyTime);
  const gameBefore = await camera(page);
  await page.locator('#mv-camera-mode').selectOption('orbit');
  const canvas = await page.locator('#mv-scene canvas').boundingBox();
  await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2);
  await page.mouse.down();
  await page.mouse.move(canvas.x + canvas.width / 2 + 90, canvas.y + canvas.height / 2 + 25, { steps: 6 });
  await page.mouse.up();
  const view = await page.evaluate(() => window.probeCtx.scene().getViewPose());
  assert.equal(view.mode, 'orbit');
  await page.screenshot({ path: path.join(evidence, 'camera-free-view-ko.png') });
  await page.keyboard.press('k');
  await page.waitForFunction(() => !!MVStudio.getState().project.editor.camera.shots['cam:1']);
  current = await state(page);
  assert.equal(current.history.undoLabel, 'Key current view');
  assert.deepEqual(current.project.editor.camera.shots['cam:1'].keys.map((key) => key.frame), [75]);
  near(current.time, keyTime, 1e-9, 'the playhead is on the keyed frame');
  await page.locator('#mv-camera-mode').selectOption('live');
  const keyed = await camera(page);
  assert(distance(keyed.position, view.position) <= 1e-3, `game camera at the view position (${distance(keyed.position, view.position)})`);
  assert(angleBetween(keyed.quaternion, view.quaternion) <= .01, `game camera along the view (${angleBetween(keyed.quaternion, view.quaternion)}°)`);
  near(keyed.fov, view.fov, 1e-6, 'the same vertical FOV on screen');
  assert(distance(keyed.position, gameBefore.position) > .05 || angleBetween(keyed.quaternion, gameBefore.quaternion) > 1, 'the orbit moved the view');

  // Undo/redo by keyboard (the timeline label takes focus without typing).
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  await page.waitForFunction(() => !MVStudio.getState().project.editor.camera.shots['cam:1']);
  await seek(page, keyTime);
  const undone = await camera(page);
  assert(distance(undone.position, gameBefore.position) < 1e-9 && angleBetween(undone.quaternion, gameBefore.quaternion) < 1e-6, 'Ctrl+Z restores the shot');
  await page.keyboard.press('Control+Shift+z');
  await page.waitForFunction(() => !!MVStudio.getState().project.editor.camera.shots['cam:1']);

  // Align view to game camera: the free camera takes the game camera's pose and lens; pulled
  // back, it shows the game camera's frustum (drawn only in the free view).
  await seek(page, keyTime);
  const game = await camera(page);
  await page.locator('#mv-cam-align').click();
  assert.equal(await page.locator('#mv-camera-mode').inputValue(), 'orbit');
  const aligned = await page.evaluate(() => window.probeCtx.scene().getViewPose());
  assert(distance(aligned.position, game.position) < 1e-9 && angleBetween(aligned.quaternion, game.quaternion) < 1e-6, 'aligned to the game camera');
  near(aligned.fov, game.fov, 1e-9, 'aligned lens');
  const middle = await page.locator('#mv-scene canvas').boundingBox();
  await page.mouse.move(middle.x + middle.width / 2, middle.y + middle.height / 2);
  for (let count = 0; count < 4; count++) await page.mouse.wheel(0, 240);
  await page.mouse.down();
  await page.mouse.move(middle.x + middle.width / 2 - 70, middle.y + middle.height / 2 - 10, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(evidence, 'camera-frustum-ko.png') });
  const inspected = await camera(page);
  assert(distance(inspected.position, game.position) > .5, 'inspect() reports the free camera in the free view');
  await page.locator('#mv-camera-mode').selectOption('live');
  near(distance((await camera(page)).position, game.position), 0, 1e-9, 'the game camera is unchanged by the free view');

  // A second key and an eased segment for the curve view.
  await seek(page, shotStart + 220 / 60);
  await page.locator('#mv-camera-fields [data-mv-cam="offset.y"]').fill('.6');
  await page.locator('#mv-camera-fields [data-mv-cam="offset.y"]').press('Tab');
  // Edited channels join the curve view (Dolly, then Pedestal: Z and Y with X); chips toggle.
  const chips = () => page.locator('.mv-cam-chip[aria-pressed=true]').evaluateAll((list) => list.map((chip) => chip.dataset.mvCamChannel));
  assert.deepEqual(await chips(), ['x', 'y', 'z']);
  await page.locator('[data-mv-cam-channel="x"]').click();
  assert.deepEqual(await chips(), ['y', 'z']);
  await page.locator('[data-mv-cam-channel="x"]').click();
  assert.deepEqual(await chips(), ['x', 'y', 'z']);
  await page.locator('#mv-cam-prev-key').click();
  await page.locator('[data-mv-cam-ease="ease-in-out"]').click();
  assert.equal(await page.locator('#mv-cam-key').isVisible(), true, 'selected key fields');
  assert.equal(await page.locator('#mv-cam-interp').inputValue(), 'bezier');
  assert.equal(await page.locator('#mv-cam-handle').inputValue(), 'flat');
  assert.equal(await page.locator('#mv-cam-key .mv-cam-key-time').textContent(), '0:01.25', 'the selected key on the header clock (shot-local)');
  assert((await page.locator('#mv-cam-curves polyline.mv-cam-curve').count()) >= 3, 'key curves drawn');
  assert((await page.locator('#mv-cam-curves polyline.mv-cam-dense').count()) >= 3, 'baked curves drawn');
  assert((await page.locator('#mv-cam-curves .mv-cam-curve-key').count()) >= 6, 'key points drawn');
  assert((await page.locator('#mv-cam-curves .mv-cam-handle').count()) >= 1, 'handles of the selected key');
  // Drag a key's value in the curve view: one undo step.
  const undoBefore = (await state(page)).history.undo;
  const point = await page.locator('#mv-cam-curves .mv-cam-curve-key.mv-selected[data-channel="y"]').boundingBox();
  await page.mouse.move(point.x + point.width / 2, point.y + point.height / 2);
  await page.mouse.down();
  await page.mouse.move(point.x + point.width / 2, point.y + point.height / 2 - 12, { steps: 5 });
  await page.mouse.up();
  current = await state(page);
  assert.equal(current.history.undo, undoBefore + 1, 'a curve drag is one undo step');
  assert.equal(current.history.undoLabel, 'Move camera key');
  // A click on a grid line seeks like a click on the plot (guides let the click through).
  const grid = await page.locator('#mv-cam-curves .mv-cam-grid').nth(1).boundingBox();
  await page.mouse.click(grid.x + grid.width * .6, grid.y + grid.height / 2);
  near((await state(page)).time, shotStart + 180 / 60, 2 / 60, 'a click on the middle grid line seeks to frame 180');
  assert.equal((await state(page)).history.undo, undoBefore + 1, 'a seek is not an edit');
  await page.screenshot({ path: path.join(evidence, 'camera-editor-ko.png') });
  // A tall window shows the whole panel at once.
  await page.setViewportSize({ width: 1400, height: 1900 });
  await page.waitForTimeout(200);
  await page.locator('#mv-panel-camera').scrollIntoViewIfNeeded();
  await page.locator('#mv-panel-camera').screenshot({ path: path.join(evidence, 'camera-panel-ko.png') });
  await page.locator('#mv-cam-curves').screenshot({ path: path.join(evidence, 'camera-curves-ko.png') });
  await page.setViewportSize({ width: 1400, height: 1000 });

  // Resize is locked for an edited shot; moving stays allowed.
  await page.locator('.mv-clip[data-event="cam:1"]').click();
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=duration]').count(), 0, 'duration locked');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=start]').count(), 1);

  // Closed, the panel skips playhead updates; opened again elsewhere, it shows the playhead shot.
  const header = () => page.locator('#mv-cam-shot').textContent();
  await seek(page, 1);
  await page.waitForFunction(() => document.getElementById('mv-cam-shot')?.textContent.startsWith('샷 1 / 2'));
  await page.locator('#mv-panel-camera > summary').click();
  assert.equal(await page.locator('#mv-panel-camera').evaluate((panel) => panel.open), false, 'closed');
  await seek(page, shotStart + 2);
  await page.locator('#mv-panel-camera > summary').click();
  await page.waitForFunction(() => /^샷 2 \/ 2 · .* · 프레임 120 \/ 300/.test(document.getElementById('mv-cam-shot')?.textContent || ''));
  const resultY = Number(await page.locator('#mv-camera-fields [data-mv-cam="absolute.y"]').inputValue());
  const bakedY = (await state(page)).project.tracks[0].events[1].values.keyframes[120].position[1];
  near(resultY, bakedY, 1e-4, 'the Result fields show the playhead shot');

  // Save → reopen keeps the editor layer and the baked samples.
  current = await state(page);
  await page.locator('#mv-save').click();
  const link = page.locator('#mv-save-result a');
  await Promise.race([link.waitFor(), page.waitForFunction(() => document.getElementById('mv-status').classList.contains('mv-error'))]);
  assert.equal(await page.locator('#mv-status.mv-error').count(), 0, 'save: ' + await page.locator('#mv-status').textContent());
  const restored = await page.request.post(url + '/api/mv-studio/open', { data: { path: await link.getAttribute('title') } }).then((reply) => reply.json());
  assert.deepEqual(restored.editor.camera, current.project.editor.camera, 'editor.camera saved');
  for (const id of ['cam:0', 'cam:1']) {
    const find = (value) => value.tracks[0].events.find((item) => item.id === id).values.keyframes;
    assert.deepEqual(find(restored), find(current.project), `${id} baked samples saved`);
  }

  // Every string has Korean and Japanese copy.
  const strings = await page.evaluate(() => [...new Set([...MVStudioCameraKeys.STRINGS, ...MVStudioCameraCurves.STRINGS])]);
  for (const lang of ['ko', 'ja']) {
    const table = await page.request.get(url + '/api/i18n?lang=' + lang).then((reply) => reply.json());
    const missing = strings.filter((text) => !['X', 'Y', 'Z'].includes(text) && !(text in table.strings));
    assert.deepEqual(missing, [], `${lang} copy for every camera editor string`);
  }
  // The panel follows the language switch: its summary and every control in it.
  await page.locator('#lang-select').selectOption('en');
  await page.waitForFunction(() => document.querySelector('#mv-panel-camera > summary')?.textContent === 'Camera editor');
  await page.waitForFunction(() => document.getElementById('mv-cam-key-view')?.textContent === 'Key current view');
  assert.equal(await page.locator('#mv-cam-shot-mode option[value="offset"]').textContent(), 'Offset keys');
  assert.match(await header(), /^Shot 2 \/ 2 · .* · Frame 120 \/ 300/);
  assert.equal(await page.locator('#mv-camera-fields [data-mv-cam="offset.z"]').evaluate((input) => input.closest('label').textContent), 'Dolly');
  await page.screenshot({ path: path.join(evidence, 'camera-panel-en.png') });
  const japanese = await page.request.get(url + '/api/i18n?lang=ja').then((reply) => reply.json());
  await page.locator('#lang-select').selectOption('ja');
  await page.waitForFunction((text) => document.getElementById('mv-cam-key-view')?.textContent === text, japanese.strings['Key current view']);
  assert.equal(await page.locator('#mv-cam-shot-mode option[value="offset"]').textContent(), japanese.strings['Offset keys']);
  await page.locator('#lang-select').selectOption('ko');
  await page.waitForFunction(() => document.getElementById('mv-cam-key-view')?.textContent === '현재 시점 키 추가');

  // Added clips. The host's Duplicate clip never hands out the id of a deleted clip, whose camera
  // record stays for undo.
  const made = await page.evaluate(() => [MVStudioCameraKeys.ensureUserShot(window.probeCtx, 9.2, 10.2).event.id,
    MVStudioCameraKeys.ensureUserShot(window.probeCtx, 10.5, 11.5).event.id]);
  assert.deepEqual(made, ['camera-editor:u1', 'camera-editor:u2']);
  await page.locator('.mv-clip[data-event="camera-editor:u1"]').click();
  await page.locator('#mv-delete-clip').click();
  await page.waitForFunction(() => !document.querySelector('.mv-clip[data-event="camera-editor:u1"]'));
  assert((await state(page)).project.editor.camera.shots['camera-editor:u1'], 'the deleted clip keeps its record for undo');
  await page.locator('.mv-clip[data-event="camera-editor:u2"]').click();
  await page.locator('#mv-duplicate-clip').click();
  await page.waitForFunction(() => MVStudio.getState().project.tracks.find((item) => item.id === 'camera-editor').events.length === 2);
  current = await state(page);
  const copyId = current.selection.event;
  const userClip = (value, id) => value.project.tracks.find((item) => item.id === 'camera-editor').events.find((item) => item.id === id);
  assert.equal(copyId, 'camera-editor:u3', 'Duplicate clip skips the id of the deleted clip');
  assert.equal(current.project.editor.camera.shots[copyId], undefined, 'the copy picks up no camera record');
  const copySamples = userClip(current, copyId).values.keyframes;
  assert.deepEqual(copySamples, userClip(current, 'camera-editor:u2').values.keyframes, 'the copy carries the samples');
  // The copy has samples, not keys: a resize and its undo leave them as they were.
  const durationField = page.locator('#mv-event-fields [data-mv-field=duration]');
  await durationField.fill('0.5');
  await durationField.press('Tab');
  current = await state(page);
  assert.equal(current.history.undoLabel, 'Resize clip');
  assert.equal(userClip(current, copyId).duration, .5);
  assert.deepEqual(userClip(current, copyId).values.keyframes, copySamples, 'a shrink does not cut the copy');
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  current = await state(page);
  assert.equal(userClip(current, copyId).duration, 1);
  assert.deepEqual(userClip(current, copyId).values.keyframes, copySamples, 'undo leaves its samples bit for bit');
  // Its first edit gives it keys (the panel offers only the Value row): a rebake keeps the edit as it
  // is, and undo gives the samples back.
  await seek(page, 11.3);
  await page.waitForFunction(() => /^샷 4 \/ 4/.test(document.getElementById('mv-cam-shot')?.textContent || ''));
  assert.equal(await page.locator('#mv-cam-shot-mode').inputValue(), 'keys');
  assert.equal(await page.locator('#mv-camera-fields [data-mv-cam^="offset."]').count(), 0, 'no offset row on an added clip');
  const valueY = page.locator('#mv-camera-fields [data-mv-cam="absolute.y"]');
  await valueY.fill('2.5');
  await valueY.press('Tab');
  await page.waitForFunction((id) => MVStudio.getState().project.editor.camera.shots[id]?.mode === 'keys', copyId);
  current = await state(page);
  assert.equal(current.history.undoLabel, 'Edit camera key');
  const claimed = userClip(current, copyId).values.keyframes;
  assert.equal(claimed[18].position[1], 2.5, 'the edit at the playhead frame');
  await page.evaluate(() => MVStudioCameraKeys.requestBake(window.probeCtx, {}));
  assert.deepEqual(userClip(await state(page), copyId).values.keyframes, claimed, 'a rebake does not stack the edit');
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  current = await state(page);
  assert.equal(current.project.editor.camera.shots[copyId], undefined);
  assert.deepEqual(userClip(current, copyId).values.keyframes, copySamples, 'undo gives the copy its samples back');
  assert.deepEqual(errors, []);
  await page.close();
}

function near(actual, expected, tolerance, message) {
  assert(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} != ${expected}`);
}

async function exportRoundTrip(browser, url) {
  if (!realTimeline || !fs.existsSync(realTimeline)) {
    console.log('real 12035 export round trip skipped (set ELICHIKA_STUDIO_TIMELINE_DIR)');
    return 'skipped';
  }
  const copy = path.join(modded, 'a-1203503-live_timeline.unity');
  fs.copyFileSync(realTimeline, copy);
  const errors = [];
  const page = await newPage(browser, errors);
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const opened = await page.request.post(url + '/api/mv-studio/open', { data: { path: copy }, timeout: 600000 }).then((reply) => reply.json());
  assert.equal(opened.nativeTimeline, true);
  await importGame(page, opened);
  const main = opened.tracks.find((track) => track.kind === 'camera' && /MainCamera$/.test(track.binding || ''));
  const shot = main.events[0];
  // The route hands the page JSON text, which writes -0 as 0: compare with that text.
  const loaded = (await state(page)).project;
  assert.deepEqual(loaded, JSON.parse(JSON.stringify(opened)), 'unedited after load');

  // An unedited project exports the original bytes.
  const exportPath = async () => {
    await page.evaluate(() => { document.getElementById('mv-save-result').hidden = true; document.getElementById('mv-save-result').replaceChildren(); });
    await page.locator('#mv-export-timeline').click();
    const link = page.locator('#mv-save-result a');
    await link.waitFor({ timeout: 600000 });
    return link.getAttribute('title');
  };
  const unedited = await exportPath();
  assert(fs.readFileSync(unedited).equals(fs.readFileSync(copy)), 'unedited export is byte-identical');
  assert.equal((await state(page)).project.editor, undefined);

  // Edit shot 0: Dolly +1 at its start and a pan key in the middle.
  await page.locator(`.mv-clip[data-event="${shot.id}"]`).click();
  await page.locator('#mv-event-fields .mv-cam-open').click();
  await page.locator('#mv-camera-fields [data-mv-cam="offset.z"]').fill('1');
  await page.locator('#mv-camera-fields [data-mv-cam="offset.z"]').press('Tab');
  await seek(page, shot.start + 200 / 60);
  await page.locator('#mv-camera-fields [data-mv-cam="offset.pan"]').fill('6');
  await page.locator('#mv-camera-fields [data-mv-cam="offset.pan"]').press('Tab');
  await page.waitForFunction((id) => MVStudio.getState().project.editor?.camera?.shots?.[id]?.keys?.length === 2, shot.id);
  const edited = (await state(page)).project;
  const baked = edited.tracks.find((track) => track.id === main.id).events[0].values.keyframes;
  assert.notDeepEqual(baked, shot.values.keyframes);
  const exported = await exportPath();
  assert.notEqual(exported, unedited);
  const parsed = await page.request.post(url + '/api/mv-studio/open', { data: { path: exported }, timeout: 600000 }).then((reply) => reply.json());
  const again = parsed.tracks.find((track) => track.id === main.id);
  const frames = again.events[0].values.keyframes;
  assert.equal(frames.length, baked.length, 'same sample count');
  let worst = { position: 0, rotation: 0, fov: 0 };
  frames.forEach((frame, index) => {
    assert.equal(frame.time, baked[index].time, 'same sample times');
    worst.position = Math.max(worst.position, distance(frame.position, baked[index].position));
    worst.rotation = Math.max(worst.rotation, angleBetween(frame.rotation, baked[index].rotation));
    worst.fov = Math.max(worst.fov, Math.abs(frame.fov - baked[index].fov));
  });
  assert(worst.position < 1e-4 && worst.rotation < 1e-3 && worst.fov < 1e-4, `re-parse matches the baked samples ${JSON.stringify(worst)}`);
  main.events.slice(1).forEach((event, index) => assert.deepEqual(again.events[index + 1].values.keyframes, event.values.keyframes, `shot ${index + 1} untouched`));
  assert.deepEqual(errors, []);
  await page.close();
  return worst;
}

async function run() {
  let browser, server;
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    await synthetic(browser, server.url);
    const roundTrip = await exportRoundTrip(browser, server.url);
    console.log(JSON.stringify({ status: 'PASS', evidence, roundTrip }));
  } finally {
    if (browser) await browser.close();
    if (server) server.processHandle.kill();
    fs.rmSync(library, { recursive: true, force: true });
    if (ownEvidence && process.exitCode === undefined) fs.rmSync(evidence, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
