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

   Split-screen sub cameras (synthetic): selecting a sub camera shot opens the editor on that
   camera (the Camera choice), an offset key moves only that shot along its own view, its key
   diamonds show on its lane, Ctrl+Z / Ctrl+Shift+Z restore and redo it, it resizes with its keys
   on their frames, and the main camera's shots stay untouched.

   Camera extrapolation (synthetic): in a gap after a shot, Loop, Ping-pong and Continue show the
   pose Unity's TimelineClip gives (the shot's own pose at the wrapped time), and None no shot.

   Real 12035 timeline (skipped unless ELICHIKA_STUDIO_TIMELINE_DIR holds
   a-1203503-live_timeline.unity; no game data in Git): an unedited project exports the
   original bytes, and the export of an edited shot re-parses to the baked samples, also
   after the edited shot is shortened by ten frames.

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

// gameProject with two split-screen sub cameras (SubCamera1: two shots, SubCamera2: one).
const SPLIT = '/EntryPoint/Live/Cameras/SplitScreenEffect/Cameras';
function splitProject(local) {
  const project = gameProject(local);
  project.name = 'Split camera MV';
  const base = project.tracks[0].events[0];
  const shot = (id, start, count, from, to) => ({ ...JSON.parse(JSON.stringify(base)), id, start, duration: (count - 1) / 60, label: id,
    values: { ...JSON.parse(JSON.stringify(base.values)), keyframes: shotSamples(count, from, to) } });
  project.tracks.push(
    { id: 'sub1', kind: 'camera', label: 'SplitScreen/SubCamera1', nativeClass: 'AnimationTrack', binding: `${SPLIT}/SubCamera1`,
      events: [shot('sub1:0', 1, 121, 60, 80), shot('sub1:1', 6, 61, 90, 100)] },
    { id: 'sub2', kind: 'camera', label: 'SplitScreen/SubCamera2', nativeClass: 'AnimationTrack', binding: `${SPLIT}/SubCamera2`,
      events: [shot('sub2:0', 1, 121, -60, -40)] });
  return project;
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
// The panel's curve view shows exactly what a new view draws from the model it was last given.
const curvesAsDrawnFresh = (page) => page.evaluate(() => {
  const { container, model } = window.curveProbe, svg = container.querySelector('svg');
  return window.curvePicture(svg) === window.curveFresh(model, container.clientWidth);
});
// The baked (dense) and key curves of the panel's curve view, by channel.
const curveLines = (page) => page.evaluate(() => {
  const svg = document.querySelector('#mv-cam-curves svg');
  const lines = (kind) => Object.fromEntries([...svg.querySelectorAll('polyline.' + kind)].map((line) => [line.dataset.channel, line.getAttribute('points')]));
  return { dense: lines('mv-cam-dense'), curve: lines('mv-cam-curve') };
});

// The curve view on its own, against a new view of the same model (the full drawing): a
// playhead-only change moves the line and keeps the drawing's nodes; a change of keys, of dense
// values (equal copies included), of the selection or of the width redraws; a resize redraws
// without a new model; without a ResizeObserver the width is read on every update.
async function curveViewCache(page) {
  const result = await page.evaluate(async () => {
    const C = MVStudioCameraCurves, saved = window.curveProbe, picture = window.curvePicture, fresh = window.curveFresh;
    const real = saved.model, last = real.count - 1, channel = real.channels[0];
    const frames = (count) => new Promise((resolve) => { const step = () => (--count ? requestAnimationFrame(step) : resolve()); requestAnimationFrame(step); });
    const box = (width) => {
      const element = document.createElement('div');
      element.style.cssText = `position: fixed; left: 0; top: 0; visibility: hidden; width: ${width}px`;
      document.body.append(element);
      return element;
    };
    const checks = {}, nodes = (view) => [...view.element.children];
    const same = (a, b) => a.length === b.length && a.every((node, index) => node === b[index]);
    try {
      const container = box(400), view = C.create(container, saved.handlers);
      const shows = (model, width = 400) => picture(view.element) === fresh(model, width);
      const m0 = { ...real, playhead: last * .25 };
      view.update(m0);
      // Drawn at the panel's width first, then at its own box's width before the next paint.
      await frames(2);
      checks.first = shows(m0);
      let before = nodes(view);
      const m1 = { ...m0, playhead: last * .75 };
      view.update(m1);
      checks.playhead = shows(m1) && same(before, nodes(view));
      const keys = m1.keys.map((key) => ({ ...key, values: { ...key.values } }));
      keys[0].values[channel] += .5;
      const m2 = { ...m1, keys };
      view.update(m2);
      checks.keys = shows(m2);
      const dense = Object.fromEntries(Object.entries(m2.dense).map(([name, values]) => [name, Float64Array.from(values)]));
      dense[channel][Math.floor(last / 2)] += 3;
      const m3 = { ...m2, dense };
      view.update(m3);
      checks.dense = shows(m3);
      const other = m3.keys.find((key) => key.frame !== m3.selected).frame;
      const m4 = { ...m3, selected: other };
      view.update(m4);
      checks.selected = shows(m4) && view.element.querySelector(`.mv-cam-curve-key.mv-selected[data-frame="${other}"]`) !== null;
      before = nodes(view);
      const m5 = { ...m4, playhead: last * .5, dense: Object.fromEntries(Object.entries(m4.dense).map(([name, values]) => [name, Float64Array.from(values)])) };
      view.update(m5);
      checks.equalCopies = shows(m5) && same(before, nodes(view));
      container.style.width = '300px';
      await frames(3);
      checks.resize = shows(m5, 300);
      container.remove();
      // No ResizeObserver (older WebViews): the width is read on every update.
      const Observer = window.ResizeObserver;
      window.ResizeObserver = undefined;
      const plainBox = box(400);
      let plain;
      try { plain = C.create(plainBox, saved.handlers); } finally { window.ResizeObserver = Observer; }
      plain.update(m5);
      plainBox.style.width = '300px';
      const m6 = { ...m5, playhead: last * .25 };
      plain.update(m6);
      checks.plainWidth = picture(plain.element) === fresh(m6, 300);
      plainBox.remove();
      // A new view (the panel rebuilds it for each shot) reads no layout while it is updated: it
      // draws at the width the last view's container had (300 here) and keeps that drawing when
      // its own box has that width; another width is redrawn before the paint.
      const reads = (element) => {
        let count = 0;
        const own = Object.getOwnPropertyDescriptor(Element.prototype, 'clientWidth');
        Object.defineProperty(element, 'clientWidth', { configurable: true, get() { count++; return own.get.call(this); } });
        return () => count;
      };
      const seen = box(300), seenView = C.create(seen, saved.handlers);
      seenView.update(m6);
      await frames(2);
      seen.remove();
      const sameBox = box(300), sameReads = reads(sameBox), same300 = C.create(sameBox, saved.handlers);
      same300.update(m6);
      checks.noLayoutRead = sameReads() === 0;
      const kept = nodes(same300);
      await frames(2);
      checks.keptDrawing = same(kept, nodes(same300)) && picture(same300.element) === fresh(m6, 300);
      sameBox.remove();
      const wideBox = box(420), wideReads = reads(wideBox), wide = C.create(wideBox, saved.handlers);
      wide.update(m6);
      const early = wideReads();
      await frames(2);
      checks.redrawnWidth = early === 0 && picture(wide.element) === fresh(m6, 420);
      wideBox.remove();
    } finally { window.curveProbe = saved; }
    return checks;
  });
  assert.deepEqual(result, { first: true, playhead: true, keys: true, dense: true, selected: true, equalCopies: true, resize: true, plainWidth: true,
    noLayoutRead: true, keptDrawing: true, redrawnWidth: true });
}

async function newPage(browser, errors, options = {}) {
  const context = await browser.newContext({ locale: 'ko', viewport: { width: 1400, height: 1000 }, ...options });
  const page = await context.newPage();
  page.on('close', () => context.close().catch(() => {}));
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => dialog.accept());
  // A probe plugin hands the test the editor context (seek, scene) the camera editor gets.
  await page.addInitScript(() => {
    (window.MVStudioPlugins ||= []).push({ id: 'test-probe', order: 99, attach(ctx) { window.probeCtx = ctx; } });
    // The curve view the panel creates, its handlers and the last model it was given.
    let curves;
    Object.defineProperty(window, 'MVStudioCameraCurves', { configurable: true, get: () => curves, set(value) {
      curves = Object.freeze({ ...value, create(container, handlers) {
        const view = value.create(container, handlers), probe = window.curveProbe = { container, handlers, model: null };
        return { element: view.element, get dragging() { return view.dragging; },
          update(next) { probe.model = next; return view.update(next); } };
      } });
    } });
    // What a curve view shows, and the same model drawn by a new view at a given width (a full draw).
    window.curvePicture = (svg) => [svg.getAttribute('width'), svg.getAttribute('viewBox'), svg.innerHTML].join('\n');
    // The reference view reads its box's width at once (no ResizeObserver): a new view with one
    // first draws at the width the last view's container had and redraws before the paint.
    window.curveFresh = (model, width) => {
      const saved = window.curveProbe, box = document.createElement('div'), Observer = window.ResizeObserver;
      box.style.cssText = `position: fixed; left: 0; top: 0; visibility: hidden; width: ${width}px`;
      document.body.append(box);
      window.ResizeObserver = undefined;
      try {
        const view = curves.create(box, saved.handlers);
        view.update(model);
        return window.curvePicture(view.element);
      } finally { window.ResizeObserver = Observer; box.remove(); window.curveProbe = saved; }
    };
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
  // The open curve view meanwhile only moves its playhead line: the drawing keeps its nodes.
  const { list: played, curves: playedCurves } = await page.evaluate(() => new Promise((resolve) => {
    const M = window.MVStudioCameraMath, project = MVStudio.getState().project;
    const original = project.editor.originals['cam:0'].values.keyframes, list = [];
    let drawn = null;
    const curves = () => {
      const svg = document.querySelector('#mv-cam-curves svg');
      return { nodes: [...svg.children], x: svg.querySelector('.mv-cam-playhead').getAttribute('x1') };
    };
    const step = () => {
      const view = window.probeCtx.scene().inspect();
      if (view.time > .5 && !drawn) drawn = curves();
      if (view.time > .05 && view.time < 3.95) {
        const pose = M.sampleFrames(original, view.time);
        const position = M.unityToThreePosition(pose.position);
        const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(new THREE.Quaternion(...M.unityToThreeQuaternion(pose.rotation)));
        const moved = new THREE.Vector3(...view.camera.position).sub(new THREE.Vector3(...position));
        list.push({ time: view.time, length: moved.length(), along: moved.dot(forward) });
      }
      if (view.time >= 4 || list.length > 400) {
        const now = curves();
        resolve({ list, curves: { kept: !!drawn && now.nodes.length === drawn.nodes.length && now.nodes.every((node, index) => node === drawn.nodes[index]),
          moved: !!drawn && now.x !== drawn.x } });
      } else requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }));
  await page.locator('#mv-play').click();
  assert.deepEqual(playedCurves, { kept: true, moved: true }, 'playback moves the curve playhead without redrawing the curves');
  assert(await curvesAsDrawnFresh(page), 'the curve view after playback is the full drawing of its model');
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
  assert.equal(await page.locator(`.mv-lane[data-track="cam"] .mv-cam-key[data-frame="${moved}"]`).getAttribute('aria-selected'), 'true');
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
  // The curve view follows its panel's width when the stage / side panel splitter moves.
  const curveWidth = () => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => {
    const view = document.getElementById('mv-cam-curves');
    resolve({ drawn: Number(view.querySelector('svg').getAttribute('width')), room: Math.max(160, Math.round(view.clientWidth)) });
  }))));
  const curveBefore = await curveWidth();
  assert.equal(curveBefore.drawn, curveBefore.room, 'the curve view fills its panel');
  await page.locator('#mv-inspector-resizer').focus();
  await page.keyboard.press('Shift+ArrowLeft');
  await page.keyboard.press('Shift+ArrowLeft');
  const curveWider = await curveWidth();
  assert(curveWider.room >= curveBefore.room + 100, `the panel is wider (${curveBefore.room} -> ${curveWider.room})`);
  assert.equal(curveWider.drawn, curveWider.room, 'the curve view redraws at the wider panel width');
  await page.keyboard.press('Home');
  const curveBack = await curveWidth();
  assert.equal(curveBack.room, curveBefore.room);
  assert.equal(curveBack.drawn, curveBack.room, 'and at the default width again');
  // Drag a key's value in the curve view: one undo step.
  const undoBefore = (await state(page)).history.undo;
  const selectedKey = page.locator('#mv-cam-curves .mv-cam-curve-key.mv-selected[data-channel="y"]');
  await selectedKey.scrollIntoViewIfNeeded();
  const point = await selectedKey.boundingBox();
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
  // The curve view follows a bake, undo and redo, the channel chips, the offset space, the record
  // mode and the panel's width; each time it is the full drawing of its model.
  await curveViewCache(page);
  assert(await curvesAsDrawnFresh(page), 'the curve view is the full drawing of its model');
  const chip = (channel) => page.locator(`[data-mv-cam-channel="${channel}"]`);
  // The dense curves recomputed: a chip turned off and on again misses the panel's cache.
  const recomputed = async () => { await chip('x').click(); await chip('x').click(); return curveLines(page); };
  const redrawn = (before) => page.waitForFunction((points) =>
    document.querySelector('#mv-cam-curves polyline.mv-cam-dense[data-channel="y"]')?.getAttribute('points') !== points, before.dense.y, { timeout: 5000 });
  const unedited = await curveLines(page);
  assert.deepEqual(await recomputed(), unedited);
  const pedestal = page.locator('#mv-camera-fields [data-mv-cam="offset.y"]');
  await pedestal.fill('.05');
  await pedestal.press('Tab');
  await redrawn(unedited);
  const baked = await curveLines(page);
  assert.notEqual(baked.curve.y, unedited.curve.y, 'the key curve follows the edit');
  assert.deepEqual(await recomputed(), baked, 'the baked curves are the recomputed ones');
  assert(await curvesAsDrawnFresh(page));
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  await redrawn(baked);
  assert.deepEqual(await curveLines(page), unedited, 'undo draws the curves before the edit');
  await page.keyboard.press('Control+Shift+z');
  await redrawn(unedited);
  assert.deepEqual(await curveLines(page), baked, 'redo draws the edited curves');
  await page.keyboard.press('Control+z');
  await redrawn(baked);
  assert.deepEqual(await curveLines(page), unedited);
  const fovCurve = page.locator('#mv-cam-curves polyline.mv-cam-dense[data-channel="fov"]');
  assert.equal(await fovCurve.count(), 0);
  await chip('fov').click();
  assert.equal(await fovCurve.count(), 1, 'a chip turned on draws its baked curve');
  assert(await curvesAsDrawnFresh(page));
  await chip('fov').click();
  for (const [control, value] of [['#mv-cam-space', 'world'], ['#mv-cam-shot-mode', 'keys']]) {
    const before = await curveLines(page);
    await page.locator(control).selectOption(value);
    await redrawn(before);
    const shown = await curveLines(page);
    assert.deepEqual(await recomputed(), shown, `${control} = ${value}: the recomputed curves`);
    assert(await curvesAsDrawnFresh(page));
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    await redrawn(shown);
    assert.deepEqual(await curveLines(page), before, `${control} = ${value}: undo`);
  }
  await page.locator('#mv-cam-space').selectOption('view');
  const graphWidth = () => page.locator('#mv-cam-curves').evaluate((element) => ({
    drawn: element.querySelector('svg').getAttribute('width'), box: String(Math.max(160, Math.round(element.clientWidth))) }));
  const wide = await graphWidth();
  assert.equal(wide.drawn, wide.box);
  await page.locator('#mv-cam-curves').evaluate((element) => { element.style.width = '300px'; });
  await page.waitForFunction((before) => {
    const element = document.getElementById('mv-cam-curves'), drawn = element.querySelector('svg').getAttribute('width');
    return drawn !== before && drawn === String(Math.max(160, Math.round(element.clientWidth)));
  }, wide.drawn, { timeout: 5000 });
  assert(await curvesAsDrawnFresh(page), 'a narrower panel redraws the curves at its width');
  await page.locator('#mv-cam-curves').evaluate((element) => { element.style.width = ''; });
  await page.waitForFunction((width) => document.querySelector('#mv-cam-curves svg').getAttribute('width') === width, wide.drawn, { timeout: 5000 });
  await page.screenshot({ path: path.join(evidence, 'camera-editor-ko.png') });
  // A tall window shows the whole panel at once.
  await page.setViewportSize({ width: 1400, height: 1900 });
  await page.waitForTimeout(200);
  await page.locator('#mv-panel-camera').scrollIntoViewIfNeeded();
  await page.locator('#mv-panel-camera').screenshot({ path: path.join(evidence, 'camera-panel-ko.png') });
  await page.locator('#mv-cam-curves').screenshot({ path: path.join(evidence, 'camera-curves-ko.png') });
  await page.setViewportSize({ width: 1400, height: 1000 });

  // An edited shot can be moved and resized.
  await page.locator('.mv-clip[data-event="cam:1"]').click();
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=duration]').count(), 1, 'an edited shot keeps its resize');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=start]').count(), 1);

  // Closed, the panel skips playhead updates; opened again elsewhere, it shows the playhead shot.
  const header = () => page.locator('#mv-cam-shot').textContent();
  await seek(page, 1);
  await page.waitForFunction(() => document.getElementById('mv-cam-shot')?.textContent.startsWith('샷 1 / 2'));
  // Within a shot the header follows the playhead in place.
  await seek(page, 2);
  await page.waitForFunction(() => /^샷 1 \/ 2 · .* · 프레임 120 \/ 240 \(0:02\.00\)$/.test(document.getElementById('mv-cam-shot')?.textContent || ''),
    null, { timeout: 5000 });
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

async function subCameras(browser, url) {
  const errors = [];
  const page = await newPage(browser, errors);
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
  const project = splitProject(local);
  await importGame(page, project);
  await page.locator('#mv-camera-mode').waitFor();
  assert.deepEqual((await state(page)).project, project, 'the opened project is unchanged');
  const find = (value, id) => value.tracks.flatMap((track) => track.events).find((item) => item.id === id);
  const original = find(project, 'sub1:0').values.keyframes;

  // A sub camera shot opens the editor on its camera.
  await page.locator('.mv-clip[data-event="sub1:0"]').click();
  assert(await page.locator('#mv-panel-camera').evaluate((panel) => panel.open), 'selecting a sub camera shot opens the camera editor');
  await page.waitForFunction((camera) => document.getElementById('mv-cam-camera')?.value === camera, `${SPLIT}/SubCamera1`);
  assert.deepEqual(await page.locator('#mv-cam-camera option').allTextContents(), ['메인 카메라', '서브 카메라 1', '서브 카메라 2']);
  await seek(page, 1.5);
  await page.waitForFunction(() => /^샷 1 \/ 2 · sub1:0 · 프레임 30 \/ 120/.test(document.getElementById('mv-cam-shot')?.textContent || ''));
  assert.equal(await page.locator('#mv-cam-align').count(), 0, 'Align view (main camera only) is not offered');
  const dolly = page.locator('#mv-camera-fields [data-mv-cam="offset.z"]');
  await dolly.fill('1');
  await dolly.press('Tab');
  await page.waitForFunction(() => !!MVStudio.getState().project.editor?.camera?.shots?.['sub1:0']);
  let current = await state(page);
  assert.deepEqual(current.project.editor.camera.shots['sub1:0'].keys.map((key) => [key.frame, key.values.z]), [[30, 1]]);
  assert.equal(current.history.undoLabel, 'Edit camera key');
  const moved = await page.evaluate(([before, after]) => after.every((sample, index) => {
    const M = window.MVStudioCameraMath, forward = M.rotateVector(M.normalize(before[index].rotation), [0, 0, -1]);
    return sample.position.every((value, axis) => Math.abs(value - before[index].position[axis] - forward[axis]) < 1e-9);
  }), [original, find(current.project, 'sub1:0').values.keyframes]);
  assert(moved, 'every sample moved 1 m along the sub camera\'s own view');
  for (const id of ['cam:0', 'cam:1', 'sub1:1', 'sub2:0']) assert.deepEqual(find(current.project, id), find(project, id), `${id} untouched`);
  const diamond = page.locator('.mv-lane[data-track="sub1"] .mv-cam-key[data-event="sub1:0"]');
  await diamond.waitFor();
  assert.equal(await diamond.getAttribute('data-frame'), '30');
  await page.screenshot({ path: path.join(evidence, 'camera-sub-ko.png') });

  // Undo and redo.
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  current = await state(page);
  assert.equal(current.project.editor?.camera?.shots?.['sub1:0'], undefined);
  assert.deepEqual(find(current.project, 'sub1:0').values.keyframes, original, 'undo restores the sub camera samples');
  await page.keyboard.press('Control+Shift+z');
  await page.waitForFunction(() => !!MVStudio.getState().project.editor?.camera?.shots?.['sub1:0']);
  const redone = find((await state(page)).project, 'sub1:0');
  assert.notDeepEqual(redone.values.keyframes, original);

  // Resize: ten frames longer, its key stays on frame 30 and the edit covers the new frames.
  await page.locator('.mv-clip[data-event="sub1:0"]').click();
  const durationField = page.locator('#mv-event-fields [data-mv-field=duration]');
  assert.equal(await durationField.count(), 1, 'an edited shot can be resized');
  await durationField.fill(String(130 / 60));
  await durationField.press('Tab');
  await page.waitForFunction(() => MVStudio.getState().project.tracks.find((track) => track.id === 'sub1').events[0].values.keyframes.length === 131);
  current = await state(page);
  assert.deepEqual(current.project.editor.camera.shots['sub1:0'].keys.map((key) => key.frame), [30]);

  // The main camera is edited again from the Camera choice; its shots were never touched.
  await page.locator('#mv-cam-camera').selectOption('main');
  await page.waitForFunction(() => /^샷 1 \/ 2 · /.test(document.getElementById('mv-cam-shot')?.textContent || '') &&
    document.getElementById('mv-cam-align') !== null);
  for (const id of ['cam:0', 'cam:1']) assert.deepEqual(find(current.project, id), find(project, id), `${id} untouched`);

  // A key diamond on the sub camera's lane, clicked while the main camera is edited: the editor
  // switches to that camera and shot, and a field edit keys that shot.
  await page.locator('.mv-lane[data-track="sub1"] .mv-cam-key[data-event="sub1:0"][data-frame="30"]').click();
  await page.waitForFunction((camera) => document.getElementById('mv-cam-camera')?.value === camera, `${SPLIT}/SubCamera1`);
  await page.waitForFunction(() => /^샷 1 \/ 2 · sub1:0 · 프레임 30 \/ 130/.test(document.getElementById('mv-cam-shot')?.textContent || ''));
  assert.deepEqual((await page.evaluate(() => MVStudioCameraKeys.selected(window.probeCtx))).frames, [30]);
  const pedestal = page.locator('#mv-camera-fields [data-mv-cam="offset.y"]');
  await pedestal.fill('0.25');
  await pedestal.press('Tab');
  await page.waitForFunction(() => MVStudio.getState().project.editor.camera.shots['sub1:0'].keys[0].values.y === .25);
  current = await state(page);
  assert.deepEqual(current.project.editor.camera.shots['sub1:0'].keys.map((key) => [key.frame, key.values.y]), [[30, .25]]);
  assert.deepEqual(Object.keys(current.project.editor.camera.shots), ['sub1:0'], 'no main camera shot was keyed');
  // Back on the main camera, the sub camera's key is no longer selected.
  await page.locator('#mv-cam-camera').selectOption('main');
  await page.waitForFunction(() => document.getElementById('mv-cam-align') !== null);
  assert.equal(await page.evaluate(() => MVStudioCameraKeys.selected(window.probeCtx)), null);
  assert.equal(await page.locator('.mv-cam-key[aria-selected="true"]').count(), 0);
  // "Open camera editor" in the inspector (still showing sub1:0) picks the inspected clip's camera.
  assert.equal(await page.locator('#mv-event-fields .mv-cam-open').count(), 1);
  await page.locator('#mv-event-fields .mv-cam-open').click();
  await page.waitForFunction((camera) => document.getElementById('mv-cam-camera')?.value === camera, `${SPLIT}/SubCamera1`);
  await page.waitForFunction(() => document.getElementById('mv-cam-align') === null);
  assert.deepEqual(errors, []);
  await page.close();
}

// An edited shot shortened past one of its keys: the frames it keeps play as before, the key past
// its end is hidden on the lane but stays in the record and still shapes the curve view's key
// curve, and lengthening the shot again brings the key and the full bake back.
async function shortenPastKeys(browser, url) {
  const errors = [];
  const page = await newPage(browser, errors);
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
  const project = gameProject(local);
  project.name = 'Camera shorten MV';
  await importGame(page, project);
  await page.locator('#mv-camera-mode').waitFor();
  const start = 241 / 60;
  const samplesOf = async () => (await state(page)).project.tracks[0].events[1].values.keyframes;
  const storedFrames = async () => (await state(page)).project.editor.camera.shots['cam:1'].keys.map((key) => key.frame);
  const diamonds = () => page.locator('.mv-lane[data-track="cam"] .mv-cam-key[data-event="cam:1"]').evaluateAll((items) => items.map((item) => Number(item.dataset.frame)));
  await page.locator('.mv-clip[data-event="cam:1"]').click();
  const dolly = page.locator('#mv-camera-fields [data-mv-cam="offset.z"]');
  for (const [frame, value] of [[30, '1'], [250, '-2']]) {
    await seek(page, start + frame / 60);
    await page.waitForFunction((text) => (document.getElementById('mv-cam-shot')?.textContent || '').includes(text), `프레임 ${frame} / 300`);
    await dolly.fill(value);
    await dolly.press('Tab');
    await page.waitForFunction((count) => MVStudio.getState().project.editor?.camera?.shots?.['cam:1']?.keys.length === count, frame === 30 ? 1 : 2);
  }
  const full = await samplesOf();
  await page.waitForFunction(() => document.querySelectorAll('.mv-lane[data-track="cam"] .mv-cam-key[data-event="cam:1"]').length === 2);

  // 301 → 201 frames from the Duration field.
  await page.locator('.mv-clip[data-event="cam:1"]').click();
  const durationField = page.locator('#mv-event-fields [data-mv-field=duration]');
  await durationField.fill(String(200 / 60));
  await durationField.press('Tab');
  await page.waitForFunction(() => MVStudio.getState().project.tracks[0].events[1].values.keyframes.length === 201);
  assert.deepEqual(await samplesOf(), full.slice(0, 201), 'the frames the shot keeps play as before, bit for bit');
  assert.deepEqual(await storedFrames(), [30, 250], 'the key past the end stays in the record');
  await page.waitForFunction(() => document.querySelectorAll('.mv-lane[data-track="cam"] .mv-cam-key[data-event="cam:1"]').length === 1);
  assert.deepEqual(await diamonds(), [30], 'only the key on the shot has a diamond');
  await seek(page, start + 100 / 60);
  await page.waitForFunction(() => /^샷 2 \/ 2 · .* · 프레임 100 \/ 200/.test(document.getElementById('mv-cam-shot')?.textContent || ''));
  assert.equal(await page.locator('.mv-cam-note').textContent(), '이 샷의 끝 뒤에 있는 키: 1개. 숨겨져 있지만 움직임에는 계속 반영되며, 샷을 늘리면 다시 나타납니다.');
  // The curve view: one Dolly point, and its key curve runs toward the hidden key, on the baked curve.
  await page.locator('#mv-cam-curves').scrollIntoViewIfNeeded();
  assert.equal(await page.locator('#mv-cam-curves .mv-cam-curve-key[data-channel="z"]').count(), 1);
  const lines = await curveLines(page);
  const points = (text) => text.split(' ').map((pair) => pair.split(',').map(Number));
  const [key, dense] = [points(lines.curve.z), points(lines.dense.z)];
  assert.equal(key.length, dense.length);
  key.forEach(([x, y], index) => { near(x, dense[index][0], 1e-9, `x ${index}`); near(y, dense[index][1], .05, `the key curve follows the baked curve at ${index}`); });
  assert(Math.abs(key.at(-1)[1] - key[0][1]) > 5, 'past frame 30 it bends toward the hidden key');
  assert(await curvesAsDrawnFresh(page));

  // Lengthened again: the key and the full bake come back.
  await page.locator('.mv-clip[data-event="cam:1"]').click();
  await durationField.fill('5');
  await durationField.press('Tab');
  await page.waitForFunction(() => MVStudio.getState().project.tracks[0].events[1].values.keyframes.length === 301);
  assert.deepEqual(await samplesOf(), full, 'the full shot bakes as before');
  await page.waitForFunction(() => document.querySelectorAll('.mv-lane[data-track="cam"] .mv-cam-key[data-event="cam:1"]').length === 2);
  assert.deepEqual(await diamonds(), [30, 250]);
  // Undo both resizes.
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  await page.waitForFunction(() => MVStudio.getState().project.tracks[0].events[1].values.keyframes.length === 201);
  await page.keyboard.press('Control+z');
  await page.waitForFunction(() => MVStudio.getState().project.tracks[0].events[1].values.keyframes.length === 301);
  assert.equal((await state(page)).history.undoLabel, 'Edit camera key');
  assert.deepEqual(await samplesOf(), full);
  assert.deepEqual(errors, []);
  await page.close();
}

async function extrapolation(browser, url) {
  const errors = [];
  const page = await newPage(browser, errors);
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
  const project = gameProject(local);
  project.name = 'Camera extrapolation MV';
  // cam:0 plays 0-4 s, then a 2 s gap its post-extrapolation covers, then cam:1 from 6 s.
  const [first, second] = project.tracks[0].events;
  second.start = 6;
  Object.assign(first.values, { postExtrapolationMode: 2, postExtrapolationTime: 2 });
  await importGame(page, project);
  await page.locator('#mv-camera-mode').waitFor();
  const pose = async (time) => { await seek(page, time); return { camera: await camera(page), shot: await page.evaluate(() => window.probeCtx.scene().inspect().cameraEvent) }; };
  const setMode = (mode) => page.evaluate((value) => window.probeCtx.history.apply({ label: 'Edit value',
    changes: [{ target: { kind: 'event', track: 'cam', event: 'cam:0' }, path: ['values', 'postExtrapolationMode'], after: value }] }), mode);
  // [mode, time in the gap, the time inside the shot that shows the same pose]
  for (const [mode, time, same] of [[2, 4.5, .5], [2, 5.25, 1.25], [3, 4.5, 3.5], [3, 5.25, 2.75], [4, 5, 4], [1, 5, 4]]) {
    await setMode(mode);
    const gap = await pose(time), inside = await pose(same);
    assert.equal(gap.shot && gap.shot.event, 'cam:0', `mode ${mode} at ${time}: the shot extrapolates`);
    assert.deepEqual(gap.camera.position, inside.camera.position, `mode ${mode} at ${time}: the pose at ${same}`);
    assert.deepEqual(gap.camera.quaternion, inside.camera.quaternion);
    assert.equal(gap.camera.fov, inside.camera.fov);
  }
  await setMode(0);
  const none = await pose(4.5);
  assert.notEqual(none.shot && none.shot.event, 'cam:0', 'None: the shot does not extrapolate');
  // A native shot set to Continue says that the preview holds its end pose, until it has camera
  // edits (the writer then ends its source with the shot, as the preview does).
  await page.evaluate(() => { window.probeCtx.project().nativeTimeline = true; });
  await page.locator('.mv-clip[data-event="cam:0"]').click();
  await seek(page, 1);
  const note = () => page.locator('.mv-cam-note').textContent();
  const continueNote = '계속: 미리보기는 이 샷의 마지막 포즈를 유지합니다. 카메라 클립이 샷보다 길면 게임에서는 이어서 재생될 수 있습니다.';
  await setMode(4);
  await page.waitForFunction((text) => document.querySelector('.mv-cam-note')?.textContent === text, continueNote);
  await setMode(1);
  await page.waitForFunction(() => document.querySelector('.mv-cam-note')?.textContent === '');
  await setMode(4);
  const dolly = page.locator('#mv-camera-fields [data-mv-cam="offset.z"]');
  await dolly.fill('1');
  await dolly.press('Tab');
  await page.waitForFunction(() => !!MVStudio.getState().project.editor?.camera?.shots?.['cam:0']);
  await page.waitForFunction(() => document.querySelector('.mv-cam-note')?.textContent === '');
  assert.equal(await note(), '', 'an edited shot ends with its source');
  assert.deepEqual(errors, []);
  await page.close();
}

// Several camera keys at once, in the Korean UI: Shift/Ctrl+click, Shift+Space, a Shift+drag box on
// the camera lane and a box in the curve view, Ctrl+A (not in a text field), Escape; a group drag
// (stopped by the next key), arrow keys, a curve-view drag of a selected key's value, Alt+drag and
// the time scale box, Delete, copy and paste into another shot (clipped to it), the offset box; each
// one undo step, and Ctrl+Z / Ctrl+Shift+Z give back the records, the baked samples and the
// selection exactly. Also the undo/redo buttons' shortcut tooltips and their names on a wide screen.
async function multiKeys(browser, url) {
  const errors = [];
  const page = await newPage(browser, errors);
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
  const project = gameProject(local);
  project.name = 'Camera keys MV';
  await importGame(page, project);
  await page.locator('#mv-camera-mode').waitFor();
  await page.locator('#mv-zoom').selectOption('96');
  // Keys on cam:0 at 0, 30, 60, 90 and 150 (Pedestal 0.1 … 0.5) and on cam:1 at 0 and 100.
  await page.evaluate(() => {
    const K = MVStudioCameraKeys, ctx = window.probeCtx;
    [[0, .1], [30, .2], [60, .3], [90, .4], [150, .5]].forEach(([frame, y]) => K.setChannels(ctx, 'offset', { y }, { time: frame / 60 }));
    [[0, .1], [100, .2]].forEach(([frame, y]) => K.setChannels(ctx, 'offset', { y }, { time: 241 / 60 + frame / 60 }));
    K.selectKey(ctx, 'cam:0', 0);
  });
  await page.locator('.mv-clip[data-event="cam:0"]').click();
  await page.locator('#mv-panel-camera').evaluate((panel) => { panel.open = true; });
  const K = (method, ...args) => page.evaluate(([name, rest]) => MVStudioCameraKeys[name](window.probeCtx, ...rest), [method, args]);
  const selected = async () => { const value = await K('selected'); return value ? [value.event, ...value.frames] : []; };
  const record = (id = 'cam:0') => page.evaluate((key) => MVStudio.getState().project.editor.camera.shots[key], id);
  const frames = async (id = 'cam:0') => (await record(id)).keys.map((key) => key.frame);
  const diamond = (frame, id = 'cam:0') => page.locator(`.mv-lane[data-track="cam"] .mv-cam-key[data-event="${id}"][data-frame="${frame}"]`);
  const undoCount = async () => (await state(page)).history.undo;
  const ariaSelected = () => page.locator('.mv-lane[data-track="cam"] .mv-cam-key[aria-selected="true"]').evaluateAll((list) => list.map((item) => Number(item.dataset.frame)));
  const center = async (locator) => { const box = await locator.boundingBox(); return { x: box.x + box.width / 2, y: box.y + box.height / 2 }; };
  const drag = async (from, dx, dy = 0, { modifiers = [] } = {}) => {
    for (const key of modifiers) await page.keyboard.down(key);
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(from.x + dx / 2, from.y + dy / 2, { steps: 4 });
    await page.mouse.move(from.x + dx, from.y + dy, { steps: 4 });
    await page.mouse.up();
    for (const key of modifiers) await page.keyboard.up(key);
  };
  const shortcut = async (keys) => { await page.locator('#mv-timeline-label').click(); for (const key of [].concat(keys)) await page.keyboard.press(key); };

  // The list box of keys and its options.
  assert.equal(await page.locator('.mv-lane[data-track="cam"] .mv-cam-keylist').first().getAttribute('role'), 'listbox');
  assert.equal(await page.locator('.mv-lane[data-track="cam"] .mv-cam-keylist').first().getAttribute('aria-multiselectable'), 'true');
  assert.equal(await diamond(30).getAttribute('role'), 'option');
  // Click, Shift+click, Ctrl+click (toggle).
  await diamond(30).click();
  assert.deepEqual(await selected(), ['cam:0', 30]);
  await diamond(60).click({ modifiers: ['Shift'] });
  await diamond(90).click({ modifiers: ['Control'] });
  assert.deepEqual(await selected(), ['cam:0', 30, 60, 90]);
  assert.deepEqual(await ariaSelected(), [30, 60, 90], 'aria-selected on every selected diamond');
  await diamond(60).click({ modifiers: ['Control'] });
  assert.deepEqual(await selected(), ['cam:0', 30, 90], 'Ctrl+click removes');
  assert.equal(await page.locator('#mv-cam-selection-count').textContent(), '키 2개 선택됨');
  // Shift+Space adds the focused key; Escape clears.
  await diamond(150).focus();
  await page.keyboard.press('Shift+Space');
  assert.deepEqual(await selected(), ['cam:0', 30, 90, 150], 'Shift+Space adds the focused key');
  await page.keyboard.press('Escape');
  assert.deepEqual(await selected(), [], 'Escape clears the selection');
  assert.deepEqual(await ariaSelected(), []);
  // Ctrl+A on the lane: every key of that shot; in a text field it stays the field's.
  await diamond(30).focus();
  await page.keyboard.press('Control+a');
  assert.deepEqual(await selected(), ['cam:0', 0, 30, 60, 90, 150]);
  assert.equal(await page.evaluate(() => String(getSelection())), '', 'no page text selected');
  await page.locator('#mv-track-search').fill('cam');
  await page.locator('#mv-track-search').press('Control+a');
  assert.deepEqual(await page.locator('#mv-track-search').evaluate((input) => [input.selectionStart, input.selectionEnd]), [0, 3]);
  assert.deepEqual(await selected(), ['cam:0', 0, 30, 60, 90, 150], 'Ctrl+A in a text field leaves the keys alone');
  await page.locator('#mv-track-search').fill('');
  await diamond(30).focus();
  await page.keyboard.press('Escape');
  // Shift+drag over the shot: a box that adds keys, and the shot does not move.
  const start = (await state(page)).project.tracks[0].events[0].start;
  const k30 = await center(diamond(30)), k60 = await center(diamond(60));
  await drag({ x: k30.x - 20, y: k30.y + 8 }, k60.x - k30.x + 40, -14, { modifiers: ['Shift'] });
  assert.deepEqual(await selected(), ['cam:0', 30, 60], 'the box selects the keys inside it');
  assert.equal((await state(page)).project.tracks[0].events[0].start, start, 'the shot stays put');
  assert.equal(await page.locator('.mv-cam-box').count(), 0, 'the box is gone');

  // Group drag by 10 frames (96 px/s: 16 px), then stopped one frame before the key at 90.
  const initial = await record(), initialBaked = (await state(page)).project.tracks[0].events[0].values.keyframes;
  let undo = await undoCount();
  await drag(await center(diamond(30)), 16);
  assert.deepEqual(await frames(), [0, 40, 70, 90, 150], 'both keys moved by 10 frames');
  assert.deepEqual(await selected(), ['cam:0', 40, 70]);
  assert.equal(await undoCount(), undo + 1, 'one undo step');
  assert.equal((await state(page)).history.undoLabel, 'Move camera keys');
  await drag(await center(diamond(40)), 64);
  assert.deepEqual(await frames(), [0, 59, 89, 90, 150], 'stopped before the key at 90, never merged');
  // Arrow keys move the selection (Shift: 10 frames), one step each.
  await diamond(89).focus();
  await page.keyboard.press('ArrowLeft');
  assert.deepEqual(await frames(), [0, 58, 88, 90, 150]);
  await page.keyboard.press('Shift+ArrowLeft');
  assert.deepEqual(await frames(), [0, 48, 78, 90, 150]);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.frame), '78', 'the moved key keeps the focus');
  assert.equal(await undoCount(), undo + 4);
  // Curve view: dragging a selected key's Pedestal moves both by the same amount.
  const before = await record();
  const point = page.locator('#mv-cam-curves .mv-cam-curve-key[data-frame="48"][data-channel="y"]');
  await point.scrollIntoViewIfNeeded();
  await drag(await center(point), 0, -15);
  const after = await record();
  const delta = after.keys[1].values.y - before.keys[1].values.y;
  assert(delta > .01, `the dragged key moved up (${delta})`);
  near(after.keys[2].values.y - before.keys[2].values.y, delta, 1e-12, 'the other selected key by the same amount');
  for (const index of [0, 3, 4]) assert.deepEqual(after.keys[index], before.keys[index], 'unselected keys unchanged');
  assert.deepEqual(after.keys.map((key) => key.frame), before.keys.map((key) => key.frame));
  assert.equal(await undoCount(), undo + 5, 'a curve drag is one undo step');
  // A box in the curve view replaces the selection; Shift adds.
  const graph = await page.locator('#mv-cam-curves svg').boundingBox();
  const width = Number(await page.locator('#mv-cam-curves svg').getAttribute('width'));
  const graphX = (frame) => graph.x + (44 + frame / 240 * (width - 52)) * graph.width / width;
  await drag({ x: graphX(80), y: graph.y + 10 }, graphX(95) - graphX(80), 120);
  assert.deepEqual(await selected(), ['cam:0', 90], 'a curve-view box selects the keys inside it');
  await drag({ x: graphX(140), y: graph.y + 10 }, graphX(160) - graphX(140), 120, { modifiers: ['Shift'] });
  assert.deepEqual(await selected(), ['cam:0', 90, 150], 'Shift adds');
  // Stretch: Alt+drag the last selected key (around the first one), then the time scale box.
  await diamond(0).click({ modifiers: ['Shift'] });
  await diamond(48).click({ modifiers: ['Shift'] });
  assert.deepEqual(await selected(), ['cam:0', 0, 48, 90, 150]);
  await drag(await center(diamond(150)), 48, 0, { modifiers: ['Alt'] });
  assert.deepEqual(await frames(), [0, 58, 78, 108, 180], 'Alt+drag stretches 0…150 to 0…180');
  assert.equal((await state(page)).history.undoLabel, 'Scale camera key timing');
  await page.locator('#mv-cam-scale').fill('50');
  await page.locator('#mv-cam-scale-apply').click();
  // 50 % would put the key at 108 on 54, past the unselected key at 78: the scale stops just after it.
  assert.deepEqual(await frames(), [0, 42, 78, 79, 131], 'the time scale box compresses until the next key');
  assert.match(await page.locator('#mv-status').textContent(), /멈췄습니다/);
  assert.deepEqual(await selected(), ['cam:0', 0, 42, 79, 131]);
  assert.equal(await undoCount(), undo + 7);
  // Undo all of it: the record and the baked samples are the ones before, with the selection then.
  const edited = await record(), editedBaked = (await state(page)).project.tracks[0].events[0].values.keyframes;
  await shortcut(Array(7).fill('Control+z'));
  assert.deepEqual(await record(), initial, 'undo restores the keys exactly');
  assert.deepEqual((await state(page)).project.tracks[0].events[0].values.keyframes, initialBaked, 'and the baked samples');
  assert.deepEqual(await selected(), ['cam:0', 30, 60], 'and the selection made then');
  await shortcut(Array(7).fill('Control+Shift+z'));
  assert.deepEqual(await record(), edited, 'redo too');
  assert.deepEqual((await state(page)).project.tracks[0].events[0].values.keyframes, editedBaked);
  assert.deepEqual(await selected(), ['cam:0', 0, 42, 79, 131]);

  // Delete: both selected keys in one step; undo brings them back.
  await diamond(0).click();
  await diamond(42).click({ modifiers: ['Shift'] });
  undo = await undoCount();
  await diamond(42).focus();
  await page.keyboard.press('Delete');
  assert.deepEqual(await frames(), [78, 79, 131]);
  assert.equal(await undoCount(), undo + 1);
  assert.equal((await state(page)).history.undoLabel, 'Delete camera keys');
  await shortcut('Control+z');
  assert.deepEqual(await frames(), [0, 42, 78, 79, 131]);
  assert.deepEqual(await selected(), ['cam:0', 0, 42]);

  // Copy on the lane, paste at the playhead of the other shot: relative timing, clipped to it.
  await diamond(0).focus();
  await page.keyboard.press('Control+a');
  await page.keyboard.press('Control+c');
  const copied = (await record()).keys;
  await seek(page, 241 / 60 + 230 / 60);
  undo = await undoCount();
  await shortcut('Control+v');
  await page.waitForFunction(() => MVStudio.getState().project.editor.camera.shots['cam:1'].keys.length > 2);
  assert.deepEqual(await frames('cam:1'), [0, 100, 230, 272], 'pasted at 230 + 0/42; the keys 78, 79 and 131 frames later fall past 300');
  assert.equal(await undoCount(), undo + 1);
  assert.equal((await state(page)).history.undoLabel, 'Paste camera keys');
  assert.match(await page.locator('#mv-status').textContent(), /키 3개는 제외했습니다/);
  assert.deepEqual((await record('cam:1')).keys.slice(2).map((key) => key.values), copied.slice(0, 2).map((key) => key.values), 'the same offsets');
  assert.deepEqual(await selected(), ['cam:1', 230, 272]);
  assert.equal(await page.locator('#mv-cam-selection-count').textContent(), '키 2개 선택됨');
  // The offset box adds to every selected key.
  const pasted = await record('cam:1');
  await page.locator('#mv-cam-delta-y').fill('0.5');
  await page.locator('#mv-cam-delta-pan').fill('-5');
  await page.locator('#mv-cam-offset-apply').click();
  const offset = await record('cam:1');
  offset.keys.forEach((key, index) => {
    const was = pasted.keys[index].values;
    if (index < 2) assert.deepEqual(key.values, was, 'unselected keys unchanged');
    else { near(key.values.y, was.y + .5, 1e-12, 'Δ pedestal'); near(key.values.pan, was.pan - 5, 1e-12, 'Δ pan'); near(key.values.x, was.x, 0, 'x unchanged'); }
  });
  assert.equal((await state(page)).history.undoLabel, 'Offset camera keys');
  assert.equal(await page.locator('#mv-cam-delta-y').inputValue(), '', 'the boxes are emptied after the offset');
  await shortcut('Control+z');
  assert.deepEqual(await record('cam:1'), pasted, 'undo of the offset');
  await shortcut('Control+z');
  assert.deepEqual(await frames('cam:1'), [0, 100], 'undo of the paste');

  // Korean labels, the undo/redo tooltips with their shortcut, and their names on a wide screen.
  assert.equal(await page.locator('#mv-cam-selection > legend').textContent(), '키 선택');
  assert.deepEqual(await page.locator('#mv-cam-selection .mv-cam-toolbar button').evaluateAll((list) => list.map((item) => item.textContent)),
    ['여러 개 선택', '모든 키 선택', '선택 해제', '선택한 키 삭제', '키 복사', '키 붙여넣기']);
  assert.equal(await page.locator('#mv-cam-multi').getAttribute('aria-pressed'), 'false');
  assert(await page.locator('#mv-cam-selection .mv-cam-hint-mouse').isVisible(), 'the mouse hint with a fine pointer');
  assert(!(await page.locator('#mv-cam-selection .mv-cam-hint-touch').isVisible()));
  assert.equal(await page.locator('#mv-cam-scale-apply').textContent(), '간격 배율 적용');
  assert.equal(await page.locator('#mv-cam-offset-apply').textContent(), '오프셋 적용');
  assert.match(await page.locator('#mv-undo').getAttribute('title'), /^실행 취소 \(Ctrl\+Z\)\n/);
  assert.match(await page.locator('#mv-redo').getAttribute('title'), /^다시 실행 \(Ctrl\+Shift\+Z\)\n/);
  assert.equal(await page.locator('#mv-undo .mv-history-text').textContent(), '실행 취소');
  assert(await page.locator('#mv-undo .mv-history-text').isVisible(), 'the name shows next to the icon at 1400 px');
  await page.setViewportSize({ width: 412, height: 900 });
  assert(!(await page.locator('#mv-undo .mv-history-text').isVisible()), 'icon only on a narrow phone');
  await page.setViewportSize({ width: 880, height: 1000 });
  assert(await page.locator('#mv-redo .mv-history-text').isVisible(), 'the name shows on a foldable\'s inner screen');
  await page.setViewportSize({ width: 1400, height: 1000 });
  await page.locator('#mv-panel-camera').scrollIntoViewIfNeeded();
  await page.locator('#mv-panel-camera').screenshot({ path: path.join(evidence, 'camera-multikeys-panel-ko.png') });
  await page.screenshot({ path: path.join(evidence, 'camera-multikeys-ko.png') });
  assert.deepEqual(errors, []);
  await page.close();
}

// A touch drag (real touch input through the browser, so touch-action applies): `hold` ms still
// first, then `steps` moves to `to`.
async function touchDrag(page, from, to, { steps = 6, hold = 0 } = {}) {
  const cdp = await page.context().newCDPSession(page);
  const at = (point) => [{ x: point.x, y: point.y, id: 1, radiusX: 4, radiusY: 4, force: 1 }];
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: at(from) });
  if (hold) await page.waitForTimeout(hold);
  for (let step = 1; step <= steps; step++) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: at({ x: from.x + (to.x - from.x) * step / steps, y: from.y + (to.y - from.y) * step / steps }) });
    await page.waitForTimeout(16);
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await cdp.detach();
}

// Several camera keys by touch on a foldable (Galaxy Z Fold class): the cover screen (412x900 and
// 900x412) and the inner screen (880x1000 and 1000x880), touch only, DPR 2.6, Korean UI. On each:
// no sideways overflow; undo/redo reachable (named where there is room, the icon on the narrow
// cover screen); "여러 개 선택" and every selection command visible, 32 px or more and the top
// element at its centre once scrolled to; then by touch alone: turn "여러 개 선택" on, tap three keys,
// drag one (all three move, one undo step), delete them with the button, undo with the button
// (keys and selection back), drag a selected key's value in the curve view (all three change),
// long-press a key (the mode turns on, the key joins) and drag sideways along the camera lane (a
// box that adds keys, the timeline does not scroll).
async function multiKeysTouch(browser, url) {
  for (const viewport of [{ width: 412, height: 900 }, { width: 900, height: 412 }, { width: 880, height: 1000 }, { width: 1000, height: 880 }]) {
    const name = `${viewport.width}x${viewport.height}`;
    const errors = [];
    const page = await newPage(browser, errors, { viewport, isMobile: true, hasTouch: true, deviceScaleFactor: 2.6 });
    await page.goto(url + '/#mv');
    await page.waitForFunction(() => MVStudio.getState().visible);
    const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
    const project = gameProject(local);
    project.name = 'Camera keys touch';
    await importGame(page, project);
    await page.locator('#mv-camera-mode').waitFor({ state: 'attached' });
    await page.locator('#mv-zoom').selectOption('96');
    await page.evaluate(() => {
      const K = MVStudioCameraKeys, ctx = window.probeCtx;
      [[0, .1], [30, .2], [60, .3], [90, .4], [150, .5]].forEach(([frame, y]) => K.setChannels(ctx, 'offset', { y }, { time: frame / 60 }));
      K.clearSelection(ctx);
      ctx.seek(0, { audio: false });
      const panel = document.getElementById('mv-panel-camera');
      panel.open = true;
    });
    await page.waitForFunction(() => document.querySelector('#mv-cam-multi'));
    const K = (method, ...args) => page.evaluate(([key, rest]) => MVStudioCameraKeys[key](window.probeCtx, ...rest), [method, args]);
    const selected = async () => { const value = await K('selected'); return value ? value.frames : []; };
    const frames = () => page.evaluate(() => MVStudio.getState().project.editor.camera.shots['cam:0'].keys.map((key) => key.frame));
    const ys = () => page.evaluate(() => MVStudio.getState().project.editor.camera.shots['cam:0'].keys.map((key) => key.values.y));
    const undoCount = async () => (await state(page)).history.undo;
    const diamond = (frame) => page.locator(`.mv-lane[data-track="cam"] .mv-cam-key[data-event="cam:0"][data-frame="${frame}"]`);
    // Scrolled into view (centred in its scroller), its size, and whether a tap at its centre lands on it.
    const reach = (locator) => locator.evaluate((node) => {
      node.scrollIntoView({ block: 'center', inline: 'nearest' });
      const box = node.getBoundingClientRect(), x = box.left + box.width / 2, y = box.top + box.height / 2;
      const hit = document.elementFromPoint(x, y);
      return { x, y, width: box.width, height: box.height, shown: box.width > 0 && box.height > 0 && x >= 0 && x <= innerWidth && y >= 0 && y <= innerHeight,
        hit: !!hit && (hit === node || node.contains(hit)), on: hit ? (hit.id || hit.className || hit.tagName) : null };
    });
    const tap = async (locator, what) => {
      const spot = await reach(locator);
      assert(spot.shown && spot.hit, `${name}: ${what} can be tapped (${JSON.stringify(spot)})`);
      await page.touchscreen.tap(spot.x, spot.y);
      return spot;
    };
    const centre = async (locator) => { const box = await locator.boundingBox(); return { x: box.x + box.width / 2, y: box.y + box.height / 2 }; };
    const overflow = () => page.evaluate(() => ({ page: document.scrollingElement.scrollWidth - innerWidth,
      panel: (() => { const box = document.querySelector('#mv-panel-camera .mv-cam-editor'); return box ? box.scrollWidth - box.clientWidth : 0; })() }));

    assert.deepEqual(await overflow(), { page: 0, panel: 0 }, `${name}: no sideways overflow`);
    // Undo and redo: reachable; named where the row has room (touch has no tooltip).
    for (const id of ['#mv-undo', '#mv-redo']) {
      const spot = await reach(page.locator(id));
      assert(spot.shown && spot.hit && spot.width >= 31.5 && spot.height >= 31.5, `${name}: ${id} reachable, 32 px (${JSON.stringify(spot)})`);
      assert.equal(await page.locator(`${id} .mv-history-text`).isVisible(), viewport.width >= 600, `${name}: ${id} named only with room`);
    }
    assert.equal(await page.locator('#mv-undo').getAttribute('aria-label'), '실행 취소');
    // The selection section, the touch hint.
    assert(await page.locator('#mv-cam-selection .mv-cam-hint-touch').isVisible(), `${name}: the touch hint`);
    assert(!(await page.locator('#mv-cam-selection .mv-cam-hint-mouse').isVisible()));
    assert.equal(await page.locator('#mv-cam-batch').isVisible(), false, 'the batch commands wait for a selection');

    // "여러 개 선택" on, then three taps.
    let undo = await undoCount();
    await tap(page.locator('#mv-cam-multi'), '여러 개 선택');
    assert.equal(await page.locator('#mv-cam-multi').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.mv-lane[data-track="cam"]').evaluate((lane) => [lane.classList.contains('mv-cam-multi'), getComputedStyle(lane).touchAction].join()),
      'true,pan-y pinch-zoom', `${name}: the camera lane takes sideways drags`);
    for (const frame of [30, 60, 90]) await tap(diamond(frame), `key ${frame}`);
    assert.deepEqual(await selected(), [30, 60, 90], `${name}: three taps, three keys`);
    assert.deepEqual(await page.locator('.mv-lane[data-track="cam"] .mv-cam-key[aria-selected="true"]').evaluateAll((list) => list.map((node) => Number(node.dataset.frame))), [30, 60, 90]);
    assert.equal(await page.locator('#mv-cam-selection-count').textContent(), '키 3개 선택됨');
    await tap(diamond(60), 'a selected key');
    assert.deepEqual(await selected(), [30, 90], `${name}: a second tap takes a key out`);
    await tap(diamond(60), 'key 60 again');
    assert.equal(await undoCount(), undo, 'selecting is no edit');
    // Every command for the selection is shown, 32 px or more, and takes a tap.
    for (const id of ['#mv-cam-select-all', '#mv-cam-clear-selection', '#mv-cam-delete-keys', '#mv-cam-copy-keys', '#mv-cam-paste-keys',
      '#mv-cam-scale', '#mv-cam-scale-apply', '#mv-cam-delta-x', '#mv-cam-delta-pan', '#mv-cam-delta-fov', '#mv-cam-offset-apply']) {
      const spot = await reach(page.locator(id));
      assert(spot.shown && spot.hit && spot.height >= 31.5 && spot.width >= 31.5, `${name}: ${id} shown and reachable (${JSON.stringify(spot)})`);
    }
    assert.deepEqual(await overflow(), { page: 0, panel: 0 }, `${name}: no sideways overflow with the batch commands shown`);
    const keyHit = await reach(diamond(60));
    assert(keyHit.hit, `${name}: a key diamond takes the tap`);
    // The diamond's tap target is 32 px: a tap 12 px beside its centre still lands on it.
    assert.equal(await page.evaluate(({ x, y }) => document.elementFromPoint(x + 12, y)?.dataset.frame, keyHit), '60', `${name}: 32 px key target`);

    // Group drag by touch: 16 px at 96 px/s is 10 frames.
    await touchDrag(page, await centre(diamond(30)), { x: (await centre(diamond(30))).x + 16, y: (await centre(diamond(30))).y });
    assert.deepEqual(await frames(), [0, 40, 70, 100, 150], `${name}: the three keys moved together`);
    assert.deepEqual(await selected(), [40, 70, 100]);
    assert.equal(await undoCount(), undo + 1, 'one undo step');
    // Delete with the button, undo with the button.
    await tap(page.locator('#mv-cam-delete-keys'), '선택한 키 삭제');
    assert.deepEqual(await frames(), [0, 150], `${name}: the three keys deleted`);
    assert.equal((await state(page)).history.undoLabel, 'Delete camera keys');
    await tap(page.locator('#mv-undo'), '실행 취소');
    assert.deepEqual(await frames(), [0, 40, 70, 100, 150], `${name}: undo brings them back`);
    assert.deepEqual(await selected(), [40, 70, 100], `${name}: and their selection`);
    // The curve view by touch: a selected key's Pedestal dragged up changes all three by the same amount.
    const before = await ys();
    const point = page.locator('#mv-cam-curves .mv-cam-curve-key[data-frame="70"][data-channel="y"]');
    const from = await reach(point);
    assert(from.shown, `${name}: the curve point is on screen`);
    assert.equal(await page.locator('#mv-cam-curves .mv-cam-curve-hit').count() > 0, true, 'finger targets in the curve view');
    await touchDrag(page, from, { x: from.x, y: from.y - 24 });
    const after = await ys(), delta = after[2] - before[2];
    assert(delta > .01, `${name}: the dragged key went up (${delta})`);
    for (const index of [1, 3]) near(after[index] - before[index], delta, 1e-12, `${name}: key ${index} by the same amount`);
    for (const index of [0, 4]) assert.equal(after[index], before[index], 'unselected keys unchanged');
    assert.deepEqual(await frames(), [0, 40, 70, 100, 150], 'a vertical drag keeps the times');
    assert.equal(await undoCount(), undo + 2, 'the curve drag is one undo step (the delete was undone)');

    // Long-press: with the mode off and nothing selected, it turns the mode on and adds the key.
    await tap(page.locator('#mv-cam-clear-selection'), '선택 해제');
    await tap(page.locator('#mv-cam-multi'), '여러 개 선택 off');
    assert.equal(await page.locator('#mv-cam-multi').getAttribute('aria-pressed'), 'false');
    await reach(diamond(150));
    const hold = await centre(diamond(150));
    await touchDrag(page, hold, hold, { steps: 1, hold: 700 });
    assert.equal(await page.locator('#mv-cam-multi').getAttribute('aria-pressed'), 'true', `${name}: a long-press turns 여러 개 선택 on`);
    assert.deepEqual(await selected(), [150], `${name}: and selects the key`);
    // A sideways drag along the camera lane (over the shot) draws a box that adds keys; the
    // timeline keeps its scroll position and the shot does not move.
    const scroll = await page.evaluate(() => { const box = document.getElementById('mv-timeline-grid').parentElement; return [box.scrollLeft, box.scrollTop]; });
    const k40 = await centre(diamond(40)), k100 = await centre(diamond(100));
    // From frame 20, halfway to the key at 0 (outside both keys' 32 px targets), past the key at 100.
    await touchDrag(page, { x: k40.x - 32, y: k40.y }, { x: k100.x + 12, y: k40.y + 2 }, { steps: 8 });
    assert.deepEqual(await selected(), [40, 70, 100, 150], `${name}: the box adds the keys inside it`);
    assert.deepEqual(await page.evaluate(() => { const box = document.getElementById('mv-timeline-grid').parentElement; return [box.scrollLeft, box.scrollTop]; }), scroll, 'no scroll');
    assert.equal((await state(page)).project.tracks[0].events[0].start, 0, 'the shot stays put');
    assert.equal(await page.locator('.mv-cam-box').count(), 0);
    assert.deepEqual(await overflow(), { page: 0, panel: 0 }, `${name}: still no sideways overflow`);
    await page.screenshot({ path: path.join(evidence, `camera-multikeys-touch-${name}-ko.png`) });
    assert.deepEqual(errors, [], `${name}: page errors`);
    await page.close();
  }
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
  // Both keys at once (the group commands bake through the same path): Δtilt 2°, then 5 frames later.
  const group = await page.evaluate(async (id) => {
    const K = MVStudioCameraKeys, ctx = window.probeCtx, keys = () => MVStudio.getState().project.editor.camera.shots[id].keys;
    K.selectKeys(ctx, id, keys().map((key) => key.frame));
    const tilt = keys().map((key) => key.values.tilt);
    K.offsetKeys(ctx, { tilt: 2 });
    const moved = K.moveKeys(ctx, id, K.selected(ctx).frames, 5);
    await K.pending(ctx);
    return { moved, frames: keys().map((key) => key.frame), tilt: keys().map((key, index) => key.values.tilt - tilt[index]) };
  }, shot.id);
  assert.equal(group.moved, 5);
  assert.deepEqual(group.frames, [5, 205]);
  group.tilt.forEach((delta) => near(delta, 2, 1e-9, 'Δtilt on both keys'));
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

  // The edited shot ten frames shorter: it rebakes on its new grid and exports that grid. (Selected
  // through the editor: its key diamonds cover the clip.)
  await page.evaluate(([trackId, eventId]) => window.probeCtx.select(trackId, eventId), [main.id, shot.id]);
  const length = Math.round(shot.duration * 60 - 10) / 60;
  await page.locator('#mv-event-fields [data-mv-field=duration]').fill(String(length));
  await page.locator('#mv-event-fields [data-mv-field=duration]').press('Tab');
  await page.waitForFunction(([trackId, count]) => MVStudio.getState().project.tracks.find((track) => track.id === trackId).events[0].values.keyframes.length === count,
    [main.id, baked.length - 10]);
  const shorter = (await state(page)).project.tracks.find((track) => track.id === main.id).events[0];
  const resized = await page.request.post(url + '/api/mv-studio/open', { data: { path: await exportPath() }, timeout: 600000 }).then((reply) => reply.json());
  const cut = resized.tracks.find((track) => track.id === main.id).events[0];
  assert.equal(cut.duration, shorter.duration);
  assert.equal(cut.values.keyframes.length, shorter.values.keyframes.length, 'the shorter grid');
  const resizedWorst = { position: 0, rotation: 0, fov: 0 };
  cut.values.keyframes.forEach((frame, index) => {
    const want = shorter.values.keyframes[index];
    assert.equal(frame.time, want.time, 'same sample times');
    resizedWorst.position = Math.max(resizedWorst.position, distance(frame.position, want.position));
    resizedWorst.rotation = Math.max(resizedWorst.rotation, angleBetween(frame.rotation, want.rotation));
    resizedWorst.fov = Math.max(resizedWorst.fov, Math.abs(frame.fov - want.fov));
  });
  assert(resizedWorst.position < 1e-4 && resizedWorst.rotation < 1e-3 && resizedWorst.fov < 1e-4, `resized re-parse ${JSON.stringify(resizedWorst)}`);
  assert.deepEqual(errors, []);
  await page.close();
  return { worst, resized: resizedWorst };
}

async function run() {
  let browser, server;
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    await synthetic(browser, server.url);
    await subCameras(browser, server.url);
    await shortenPastKeys(browser, server.url);
    await extrapolation(browser, server.url);
    await multiKeys(browser, server.url);
    await multiKeysTouch(browser, server.url);
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
