/* MV Studio free camera views in the real workbench (Korean UI).

   Synthetic game project (stage fixture model; one performer built from the same fixture whose
   head focus part is the animated Tip bone (node 3), so the member target moves with time; a
   MainCamera AnimationTrack with one dense 60 Hz shot):
   - the bar shows only with the free camera, in Korean, with the 3D model tab's view labels;
   - for the stage centre and for the member, each view button puts the free camera on that side
     of the target: the target projects to the screen centre and the camera's direction from the
     target is the target's front / back / left / right within 1° (Unity: front +Z, the audience
     side; right +X, the members' right), at the same distance, height angle and FOV;
   - Distance (number box, slider) and FOV (number box, Shift+wheel) change only the distance or
     only the FOV; the plain wheel still dollies;
   - a member target carries the camera along only while Follow member is on;
   - nothing reaches the project, its history or the game camera;
   - Key current view after a view preset keys the shown view (the game camera then shows it);
   - every string has Korean and Japanese copy, and the bar follows a language switch;
   - on a phone, a tablet, a phone in landscape and a laptop screen the bar never covers the
     preview controls, stays one row, and every control is where a tap lands.

   Real 12035 MV (skipped unless MV_FREECAM_SERVER_ROOT is an Elichika server root that imports
   GL Android 12035 with its member; no game data in Git): the four views around the member pass
   the same checks, Korean screenshots of the bar and the four views are taken, and the native
   timeline export is byte-identical before and after using the free camera.

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

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-freecam-library-'));
const modded = path.join(library, 'modded');
const ownEvidence = !process.env.EVIDENCE_DIR;
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-freecam-browser-'));
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, 'stage-fixture.glb'), fixture().glb);
const serverRoot = process.env.MV_FREECAM_SERVER_ROOT || '';

// Unity directions (x mirrored from three) from the target to the camera for each view.
const SIDES = { front: [0, 0, 1], back: [0, 0, -1], left: [-1, 0, 0], right: [1, 0, 0] };
const LABELS_KO = ['정면', '뒤', '왼쪽', '오른쪽'];

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
  const shot = { id: 'cam:0', start: 0, duration: 240 / 60, label: '0_240',
    values: { clipIn: 0, timeScale: 1, preExtrapolationMode: 1, postExtrapolationMode: 1, preExtrapolationTime: 0, postExtrapolationTime: 1 / 60,
      playableClass: 'AnimationPlayableAsset', m_Position: { x: 0, y: 0, z: 0 }, m_Rotation: { x: 0, y: 0, z: 0, w: 1 },
      keyframes: shotSamples(241, -30, 10) },
    editableValues: ['clipIn', 'timeScale', 'preExtrapolationMode', 'postExtrapolationMode', 'preExtrapolationTime', 'postExtrapolationTime', 'keyframes'] };
  return {
    version: 1, name: 'Free camera MV', duration: 8, nativeTimeline: false, assets: local.assets, stage: local.stage, warnings: [], quality: {},
    performers: [{ id: 'actor-1', label: 'Actor 1', position: 1, glb: local.stage.glb, transform: { position: [0, 0, 0] },
      rig: { focusParts: { 0: 3 } } }],
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 79, assetId: 1 },
    tracks: [{ id: 'cam', kind: 'camera', label: 'CameraMotion/Camera1', nativeClass: 'AnimationTrack', binding: '/EntryPoint/Live/Cameras/MainCamera',
      events: [shot] }],
  };
}

async function importGame(page, project) {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
    regions: [{ id: 'gl', label: 'GL' }], platforms: [{ id: 'android', label: 'Android' }],
    songs: [{ id: 79, title: project.name, variants: [{ id: 1, label: 'MV' }] }] } }));
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
const freeState = (page) => page.evaluate(() => window.probeCtx.scene().freeView.state());
const setMode = (page, mode) => page.locator('#mv-camera-mode').selectOption(mode);
const angleBetween = (a, b) => {
  const dot = Math.abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]);
  const cross = [a[3] * b[0] - a[0] * b[3] - a[1] * b[2] + a[2] * b[1], a[3] * b[1] - a[1] * b[3] - a[2] * b[0] + a[0] * b[2],
    a[3] * b[2] - a[2] * b[3] - a[0] * b[1] + a[1] * b[0]];
  return 2 * Math.atan2(Math.hypot(...cross), dot) * 180 / Math.PI;
};
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const near = (actual, expected, tolerance, message) => assert(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} != ${expected}`);

// The shown free view against its target: where the target lands on screen (NDC), the camera's
// Unity direction from the target, its distance, height angle (deg) and FOV.
const measure = (page) => page.evaluate(() => {
  const scene = window.probeCtx.scene(), view = scene.inspect().camera;
  const target = new THREE.Vector3(...scene.freeView.targetPoint());
  const lens = new THREE.PerspectiveCamera();
  lens.position.fromArray(view.position);
  lens.quaternion.fromArray(view.quaternion);
  lens.updateMatrixWorld(true);
  lens.projectionMatrix.fromArray(view.projection);
  const ndc = target.clone().project(lens);
  const offset = new THREE.Vector3(...view.position).sub(target);
  // The orbit offset: from the point the free camera turns around (a pan can move it off the target).
  const orbit = new THREE.Vector3(...view.position).sub(new THREE.Vector3(...scene.freeView.state().orbitTarget));
  return { cameraMode: scene.inspect().cameraMode, ndc: [ndc.x, ndc.y, ndc.z], unity: [-offset.x, offset.y, offset.z], distance: offset.length(),
    orbitDistance: orbit.length(), orbitElevation: Math.asin(orbit.y / orbit.length()) * 180 / Math.PI,
    fov: view.fov, target: target.toArray(), position: view.position, quaternion: view.quaternion };
});

// Degrees between the horizontal Unity direction `unity` and `side`.
function sideError(unity, side) {
  const a = Math.atan2(unity[0], unity[2]), b = Math.atan2(side[0], side[2]);
  let delta = Math.abs(a - b) * 180 / Math.PI;
  if (delta > 180) delta = 360 - delta;
  return delta;
}

// Clicks each view button and checks the view; returns the measurements.
async function checkViews(page, label, screenshot) {
  const results = {};
  for (const view of Object.keys(SIDES)) {
    const before = await measure(page);
    await page.locator(`[data-mv-freecam-view="${view}"]`).click();
    const after = await measure(page);
    assert.equal(after.cameraMode, 'orbit');
    assert(Math.abs(after.ndc[0]) < 1e-4 && Math.abs(after.ndc[1]) < 1e-4 && Math.abs(after.ndc[2]) < 1,
      `${label} ${view}: the target is at the screen centre (${after.ndc})`);
    const error = sideError(after.unity, SIDES[view]);
    assert(error < 1, `${label} ${view}: the camera is on the ${view} side (${error}°, ${after.unity})`);
    near(after.distance, before.orbitDistance, 1e-6, `${label} ${view}: same distance`);
    near(after.orbitElevation, before.orbitElevation, 1e-6, `${label} ${view}: same height angle`);
    assert.equal(after.fov, before.fov, `${label} ${view}: same FOV`);
    results[view] = { sideError: error, ndc: after.ndc.slice(0, 2), distance: after.distance, elevation: after.orbitElevation };
    if (screenshot) await screenshot(view);
  }
  return results;
}

async function newPage(browser, errors, viewport = { width: 1400, height: 1000 }, device = {}) {
  const context = await browser.newContext({ locale: 'ko', viewport, ...device });
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => dialog.accept());
  // A probe plugin hands the test the editor context (seek, scene) the plugins get.
  await page.addInitScript(() => {
    (window.MVStudioPlugins ||= []).push({ id: 'test-probe', order: 99, attach(ctx) { window.probeCtx = ctx; } });
  });
  return page;
}

// Opens the workbench and imports the synthetic game project; returns the project.
async function openSynthetic(page, url) {
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  const local = await page.request.post(url + '/api/mv-studio/open', { data: { path: path.join(modded, 'stage-fixture.glb') } }).then((reply) => reply.json());
  assert(local.stage && local.stage.glb, 'the stage fixture opens');
  const project = gameProject(local);
  await importGame(page, project);
  await page.waitForFunction(() => window.probeCtx.scene()?.freeView.targets().some((item) => item.id === 'member:1'));
  return project;
}

const frames = (page) => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));

// Where the preview, the view, the preview controls and the bar are, and whether a tap at the
// centre of each control reaches it. The target list and the view buttons are hit where they
// are (or, with `swipe`, after a sideways scroll); the rest of the bar may need that scroll.
function layoutProbe(swipe = false) {
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height };
  };
  const hit = (element, scroll = false) => {
    if (scroll) element.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    const rect = element.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return !!top && (top === element || element.contains(top));
  };
  const bar = document.getElementById('mv-free-camera');
  const controls = ['mv-camera-mode', 'mv-screen-fade', 'mv-frame-scene', 'mv-freecam-target'].map((id) => [id, document.getElementById(id)]);
  const views = [...bar.querySelectorAll('[data-mv-freecam-view]')].map((element) => [element.dataset.mvFreecamView, element]);
  const result = { preview: box(document.querySelector('.mv-preview')), scene: box(document.getElementById('mv-scene')),
    controls: box(document.getElementById('mv-preview-controls')), bar: box(bar), classes: [...bar.classList],
    rows: [...bar.children].filter((child) => child.getClientRects().length).map(box),
    hits: Object.fromEntries([...controls, ...views].map(([name, element]) => [name, hit(element, swipe && bar.contains(element))])) };
  result.scrolled = Object.fromEntries(['mv-freecam-distance', 'mv-freecam-fov', 'mv-freecam-follow'].map((id) => [id, hit(document.getElementById(id), true)]));
  bar.scrollLeft = 0;
  return result;
}

const apart = (a, b) => a.left >= b.right - .5 || a.right <= b.left + .5 || a.top >= b.bottom - .5 || a.bottom <= b.top + .5;
const inside = (a, b) => a.left >= b.left - .5 && a.right <= b.right + .5 && a.top >= b.top - .5 && a.bottom <= b.bottom + .5;

// Phones and a tablet (touch) and a laptop screen, each with the export note above the
// workspace (a shorter preview, as after an export). The bar never covers the preview controls:
// it is one row at the bottom of the view, or, in a preview too short for both, beside the
// controls. The view keeps the whole preview (the game camera's canvas). The preview controls,
// the target list and every view button are where a tap lands (beside the controls, after a
// sideways swipe), and a tap on a view button turns the free camera to that side.
const LAYOUTS = [
  { name: 'phone', viewport: { width: 390, height: 844 }, touch: true, place: 'bottom' },
  { name: 'tablet', viewport: { width: 768, height: 1024 }, touch: true, place: 'bottom' },
  { name: 'landscape-phone', viewport: { width: 932, height: 430 }, touch: true, place: 'beside', swipe: true },
  { name: 'laptop', viewport: { width: 1280, height: 720 }, touch: false, place: 'bottom' },
];

async function layouts(browser, url) {
  const results = {};
  for (const layout of LAYOUTS) {
    const errors = [];
    const page = await newPage(browser, errors, layout.viewport, layout.touch ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {});
    const label = `${layout.name} ${layout.viewport.width}x${layout.viewport.height}`;
    await openSynthetic(page, url);
    await page.evaluate(() => {
      const status = document.getElementById('mv-status');
      status.hidden = false;
      status.textContent = '게임용 타임라인을 내보냈습니다.';
      const note = document.getElementById('mv-save-result');
      note.hidden = false;
      note.replaceChildren(Object.assign(document.createElement('a'), { href: '#', textContent: 'A song for You- You- You-6c3fc246.unity' }));
    });
    await setMode(page, 'orbit');
    await page.locator('#mv-free-camera').waitFor({ state: 'visible' });
    await frames(page);
    const shown = await page.evaluate(layoutProbe, !!layout.swipe);
    assert(apart(shown.bar, shown.controls), `${label}: the bar does not cover the preview controls (${JSON.stringify([shown.bar, shown.controls])})`);
    assert(inside(shown.bar, shown.preview), `${label}: the bar stays inside the preview`);
    if (layout.place === 'bottom') {
      assert(!shown.classes.includes('mv-freecam-beside'), `${label}: at the bottom of the view`);
      assert(Math.abs(shown.bar.bottom - (shown.preview.bottom - 8)) < .5 && Math.abs(shown.bar.left - (shown.preview.left + 8)) < .5, `${label}: bottom left`);
      assert(shown.bar.top >= shown.controls.bottom, `${label}: below the preview controls`);
    } else {
      assert(shown.classes.includes('mv-freecam-beside'), `${label}: beside the preview controls`);
      assert(shown.bar.left >= shown.controls.right, `${label}: right of the preview controls`);
    }
    assert.deepEqual(shown.scene, shown.preview, `${label}: the view keeps the whole preview`);
    const missed = Object.entries({ ...shown.hits, ...shown.scrolled }).filter(([, reached]) => !reached).map(([name]) => name);
    assert.deepEqual(missed, [], `${label}: every control is where a tap lands`);
    const row = shown.rows[0];
    assert(shown.rows.every((item) => item.top < row.bottom && item.bottom > row.top), `${label}: one row`);
    await page.screenshot({ path: path.join(evidence, `freecam-layout-${layout.name}-ko.png`) });
    // A tap on a view button turns the view; the preview controls still switch the camera.
    const left = page.locator('[data-mv-freecam-view="left"]');
    if (layout.touch) await left.tap(); else await left.click();
    const view = await measure(page);
    assert(sideError(view.unity, SIDES.left) < 1 && Math.abs(view.ndc[0]) < 1e-4 && Math.abs(view.ndc[1]) < 1e-4, `${label}: the Left view`);
    await setMode(page, 'live');
    await page.locator('#mv-free-camera').waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => document.elementFromPoint(...(({ left, top, width, height }) => [left + width / 2, top + height / 2])(
      document.getElementById('mv-camera-mode').getBoundingClientRect())) === document.getElementById('mv-camera-mode')), true, `${label}: back to the game camera`);
    assert.deepEqual(errors, []);
    results[layout.name] = { place: shown.classes.includes('mv-freecam-beside') ? 'beside' : 'bottom', compact: shown.classes.filter((name) => /compact|tight/.test(name)),
      preview: [shown.preview.width, shown.preview.height], bar: [shown.bar.left - shown.preview.left, shown.bar.top - shown.preview.top, shown.bar.width, shown.bar.height] };
    await page.context().close();
  }
  return results;
}

async function synthetic(browser, url) {
  const errors = [];
  const page = await newPage(browser, errors);
  const project = await openSynthetic(page, url);
  const bar = page.locator('#mv-free-camera');

  // The game camera and the project before any free camera use.
  const gameTimes = [0, 1.25, 3.5];
  const gameBefore = [];
  for (const time of gameTimes) { await seek(page, time); gameBefore.push(await camera(page)); }
  assert.deepEqual((await state(page)).project, project, 'the opened project is unchanged');

  // Shown only with the free camera, in Korean, with the 3D model tab's view labels.
  assert.equal(await bar.isHidden(), true, 'hidden with the game camera');
  await setMode(page, 'orbit');
  await bar.waitFor({ state: 'visible' });
  assert.equal(await bar.getAttribute('aria-label'), '자유 카메라 시점');
  assert.deepEqual(await page.locator('[data-mv-freecam-view]').allTextContents(), LABELS_KO);
  assert.equal(await page.locator('[data-mv-freecam-view="front"]').getAttribute('title'), '관객석 쪽(멤버가 바라보는 쪽)에서 봅니다.');
  assert.deepEqual(await page.locator('#mv-freecam-target option').allTextContents(), ['무대 중앙', '1 · Actor 1']);
  assert.equal(await page.locator('#mv-freecam-target').inputValue(), 'stage');
  assert.equal(await page.locator('#mv-freecam-follow').isDisabled(), true, 'Follow member needs a member target');
  assert.equal(await page.locator('#mv-free-camera button', { hasText: '화면에 맞춤' }).count(), 0, 'no fit-to-screen');
  assert.equal(await page.locator('#mv-free-camera').evaluate((node) => node.textContent.includes('거리') && node.textContent.includes('화각')), true);

  // Views around the stage centre, then around the member.
  await seek(page, 1);
  const stageViews = await checkViews(page, 'stage centre');
  assert.deepEqual(await page.evaluate(() => window.probeCtx.scene().freeView.targetPoint('stage')), [0, 1, 0]);
  await page.locator('#mv-freecam-target').selectOption('member:1');
  let free = await freeState(page);
  assert.equal(free.target, 'member:1');
  const memberPoint = await page.evaluate(() => window.probeCtx.scene().freeView.targetPoint());
  assert(distance(free.orbitTarget, memberPoint) < 1e-9, 'the member becomes the orbit target');
  let shown = await measure(page);
  assert(Math.abs(shown.ndc[0]) < 1e-4 && Math.abs(shown.ndc[1]) < 1e-4, 'picking the member centres it');
  assert.equal(await page.locator('#mv-freecam-follow').isDisabled(), false);
  const memberViews = await checkViews(page, 'member');
  await page.locator('[data-mv-freecam-view="front"]').click();
  await page.evaluate(() => document.activeElement?.blur());
  await page.screenshot({ path: path.join(evidence, 'freecam-synthetic-ko.png') });
  await bar.screenshot({ path: path.join(evidence, 'freecam-bar-synthetic-ko.png') });

  // Distance: number box and slider change only the distance.
  const before = await measure(page);
  const distanceBox = page.locator('#mv-freecam-distance');
  await distanceBox.fill('2.5');
  await distanceBox.press('Tab');
  let after = await measure(page);
  near(after.distance, 2.5, 1e-9, 'Distance sets the distance');
  assert(angleBetween(after.quaternion, before.quaternion) < 1e-6, 'Distance keeps the direction');
  assert.deepEqual(after.target, before.target);
  assert.equal(after.fov, before.fov, 'Distance keeps the FOV');
  assert(Math.abs(after.ndc[0]) < 1e-6 && Math.abs(after.ndc[1]) < 1e-6);
  const slider = page.locator('#mv-freecam-distance-slider');
  const step = Number(await slider.inputValue());
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  after = await measure(page);
  near(after.distance, await page.evaluate((value) => MVStudioFreeCamera.metresOf(value), step + 1), 1e-9, 'the slider dollies on its log scale');
  assert(angleBetween(after.quaternion, before.quaternion) < 1e-6 && after.fov === before.fov);
  await page.waitForFunction((value) => document.getElementById('mv-freecam-distance').value === value, String(Number(after.distance.toFixed(2))));

  // FOV: number box and Shift+wheel change only the FOV; the plain wheel dollies.
  const lens = await measure(page);
  const fovBox = page.locator('#mv-freecam-fov');
  await fovBox.fill('30');
  await fovBox.press('Tab');
  after = await measure(page);
  assert.equal(after.fov, 30, 'FOV sets the lens');
  assert.deepEqual(after.position, lens.position, 'FOV keeps the position');
  assert(angleBetween(after.quaternion, lens.quaternion) < 1e-9, 'FOV keeps the direction');
  near(after.distance, lens.distance, 1e-9, 'FOV keeps the distance');
  assert.equal(await page.locator('#mv-freecam-fov-slider').inputValue(), '30');
  const canvas = await page.locator('#mv-scene canvas').boundingBox();
  await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + canvas.height / 3);
  await page.keyboard.down('Shift');
  await page.mouse.wheel(0, 200);
  await page.keyboard.up('Shift');
  await page.waitForFunction(() => window.probeCtx.scene().freeView.state().fov !== 30);
  after = await measure(page);
  assert(after.fov > 30, `Shift+wheel down widens the lens (${after.fov})`);
  assert.deepEqual(after.position, lens.position, 'Shift+wheel does not dolly');
  near(after.distance, lens.distance, 1e-9, 'Shift+wheel keeps the distance');
  await page.waitForFunction((fov) => document.getElementById('mv-freecam-fov').value === String(Number(fov.toFixed(1))), after.fov);
  const widened = after.fov;
  await page.mouse.wheel(0, -200);
  await page.waitForFunction((value) => window.probeCtx.scene().freeView.state().distance < value - 1e-6, after.distance);
  after = await measure(page);
  assert.equal(after.fov, widened, 'the plain wheel keeps the FOV');
  assert(angleBetween(after.quaternion, lens.quaternion) < 1e-6, 'and dollies along the view');

  // Follow member: the member moves between 0 s and 0.5 s (its Tip bone swings).
  await seek(page, 0);
  const pointAt0 = await page.evaluate(() => window.probeCtx.scene().freeView.targetPoint());
  const still = await measure(page);
  await seek(page, .5);
  const pointAtHalf = await page.evaluate(() => window.probeCtx.scene().freeView.targetPoint());
  const moved = distance(pointAt0, pointAtHalf);
  assert(moved > .3, `the member target moves (${moved} m)`);
  assert.deepEqual((await measure(page)).position, still.position, 'Follow member off: the view stays where it was put');
  assert.equal(await page.locator('#mv-freecam-follow').isChecked(), false, 'off by default');
  await seek(page, 0);
  await page.locator('#mv-freecam-follow').check();
  assert.equal((await freeState(page)).follow, true);
  const followed0 = await measure(page);
  await seek(page, .5);
  const followedHalf = await measure(page);
  const shift = followedHalf.position.map((value, axis) => value - followed0.position[axis]);
  const memberShift = pointAtHalf.map((value, axis) => value - pointAt0[axis]);
  assert(distance(shift, memberShift) < 1e-6, `Follow member on: the camera moves with the member (${shift} vs ${memberShift})`);
  assert(angleBetween(followedHalf.quaternion, followed0.quaternion) < 1e-9, 'and keeps its direction');
  assert(Math.abs(followedHalf.ndc[0] - followed0.ndc[0]) < 1e-6 && Math.abs(followedHalf.ndc[1] - followed0.ndc[1]) < 1e-6, 'the member stays put on screen');
  await page.locator('#mv-freecam-follow').uncheck();
  await seek(page, 0);
  assert.deepEqual((await measure(page)).position, followedHalf.position, 'off again: the view stays');
  // The stage centre never moves the camera, and the follow box is disabled for it.
  await page.locator('#mv-freecam-follow').check();
  await page.locator('#mv-freecam-target').selectOption('stage');
  assert.equal(await page.locator('#mv-freecam-follow').isDisabled(), true);
  const stageHeld = await measure(page);
  await seek(page, .5);
  assert.deepEqual((await measure(page)).position, stageHeld.position, 'the stage centre does not follow anything');
  await page.locator('#mv-freecam-target').selectOption('member:1');
  await page.locator('#mv-freecam-follow').uncheck();

  // Nothing reached the project, its history or the game camera.
  let current = await state(page);
  assert.deepEqual(current.project, project, 'the project is unchanged');
  assert.deepEqual([current.history.undo, current.history.redo], [0, 0], 'no history step');
  await setMode(page, 'live');
  assert.equal(await bar.isHidden(), true, 'hidden again with the game camera');
  for (const [index, time] of gameTimes.entries()) {
    await seek(page, time);
    assert.deepEqual(await camera(page), gameBefore[index], `t=${time}: the game camera is untouched`);
  }

  // Key current view keys the shown view: a member's right view at 1.25 s.
  await page.locator('.mv-clip[data-event="cam:0"]').click();
  await page.locator('#mv-panel-camera').evaluate((panel) => { panel.open = true; });
  await setMode(page, 'orbit');
  await seek(page, 1.25);
  await page.locator('[data-mv-freecam-view="right"]').click();
  const view = await page.evaluate(() => window.probeCtx.scene().getViewPose());
  await page.keyboard.press('k');
  await page.waitForFunction(() => !!MVStudio.getState().project.editor?.camera?.shots?.['cam:0']);
  current = await state(page);
  assert.equal(current.history.undoLabel, 'Key current view');
  await setMode(page, 'live');
  const keyed = await camera(page);
  assert(distance(keyed.position, view.position) <= 1e-3, `the game camera at the shown view (${distance(keyed.position, view.position)} m)`);
  assert(angleBetween(keyed.quaternion, view.quaternion) <= .01, `along the shown view (${angleBetween(keyed.quaternion, view.quaternion)}°)`);
  near(keyed.fov, view.fov, 1e-6, 'with the shown FOV');
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('Control+z');
  assert.deepEqual(await camera(page), gameBefore[1], 'Ctrl+Z gives the shot back');

  // Every string has Korean and Japanese copy; the bar follows a language switch.
  await setMode(page, 'orbit');
  const strings = await page.evaluate(() => MVStudioFreeCamera.STRINGS);
  for (const lang of ['ko', 'ja']) {
    const table = await page.request.get(url + '/api/i18n?lang=' + lang).then((reply) => reply.json());
    assert.deepEqual(strings.filter((text) => !(text in table.strings)), [], `${lang} copy for every free camera string`);
  }
  await page.locator('#lang-select').selectOption('en');
  await page.waitForFunction(() => document.querySelector('[data-mv-freecam-view="left"]')?.textContent === 'Left side');
  assert.deepEqual(await page.locator('[data-mv-freecam-view]').allTextContents(), ['Front', 'Back', 'Left side', 'Right side']);
  assert.equal(await page.locator('#mv-freecam-target option[value="stage"]').textContent(), 'Stage centre');
  await page.waitForFunction(() => document.querySelector('[data-mv-freecam-view="right"]')?.title === "Look from the members' right.");
  assert.equal(await bar.getAttribute('aria-label'), 'Free camera views');
  const japanese = await page.request.get(url + '/api/i18n?lang=ja').then((reply) => reply.json());
  await page.locator('#lang-select').selectOption('ja');
  await page.waitForFunction((text) => document.querySelector('[data-mv-freecam-view="front"]')?.textContent === text, japanese.strings.Front);
  assert.equal(await page.locator('.mv-freecam-follow span').textContent(), japanese.strings['Follow member']);
  // Titles and labels follow once the MV tab re-renders for the language (after app.js's text).
  await page.waitForFunction((text) => document.querySelector('.mv-freecam-follow')?.title === text, japanese.strings[strings[strings.length - 1]]);
  assert.equal(await bar.getAttribute('aria-label'), japanese.strings['Free camera views']);
  await page.locator('#lang-select').selectOption('ko');
  await page.waitForFunction(() => document.querySelector('[data-mv-freecam-view="front"]')?.textContent === '정면');
  assert.deepEqual(errors, []);
  await page.context().close();
  return { stageViews, memberViews, memberMoved: moved };
}

// The real 12035 MV through the editor's own game import (Elichika server root).
async function real(browser) {
  if (!serverRoot) {
    console.log('real 12035 views skipped (set MV_FREECAM_SERVER_ROOT to an Elichika server root)');
    return 'skipped';
  }
  const capture = require('./mv_frame_capture');
  const server = await capture.bootEditor(path.resolve(serverRoot), library, path.join(evidence, 'server-12035.log'));
  const errors = [];
  try {
    const page = await newPage(browser, errors, { width: 1600, height: 1000 });
    await page.goto(server.url + '/#mv');
    await capture.importOriginal(page, { region: 'gl', platform: 'android', liveId: 12035, assetId: 1203503 }, true);
    await page.waitForFunction(() => window.probeCtx.scene()?.freeView.targets().some((item) => item.kind === 'member'), null, { timeout: 600000 });
    // A taller preview for the screenshots: the timeline gives up some height.
    await page.locator('#mv-timeline-resizer').focus();
    for (let count = 0; count < 5; count++) await page.keyboard.press('Shift+ArrowDown');
    await page.waitForTimeout(1500);
    const time = 30;
    const exportTimeline = async () => {
      await page.evaluate(() => { document.getElementById('mv-save-result').hidden = true; document.getElementById('mv-save-result').replaceChildren(); });
      await page.locator('#mv-export-timeline').click();
      const link = page.locator('#mv-save-result a');
      await link.waitFor({ timeout: 600000 });
      return fs.readFileSync(await link.getAttribute('title'));
    };
    const exportedBefore = await exportTimeline();
    // The export note above the workspace changes the preview's size: measure after it.
    await seek(page, time);
    const gameBefore = await camera(page);
    const before = await state(page);

    await setMode(page, 'orbit');
    const member = (await page.evaluate(() => window.probeCtx.scene().freeView.targets())).find((item) => item.kind === 'member');
    await page.locator('#mv-freecam-target').selectOption(member.id);
    const label = await page.locator('#mv-freecam-target option:checked').textContent();
    const views = await checkViews(page, '12035 member', async (view) => {
      await page.waitForTimeout(300);
      await page.locator('.mv-preview').screenshot({ path: path.join(evidence, `freecam-12035-${view}-ko.png`) });
    });
    await page.locator('[data-mv-freecam-view="front"]').click();
    await page.locator('#mv-freecam-distance').fill('2.2');
    await page.locator('#mv-freecam-distance').press('Tab');
    await page.locator('#mv-freecam-fov').fill('35');
    await page.locator('#mv-freecam-fov').press('Tab');
    await page.evaluate(() => document.activeElement?.blur());
    await page.waitForTimeout(300);
    await page.locator('#mv-free-camera').screenshot({ path: path.join(evidence, 'freecam-bar-12035-ko.png') });
    await page.screenshot({ path: path.join(evidence, 'freecam-12035-page-ko.png') });
    await page.locator('#mv-freecam-follow').check();
    await seek(page, time + 4);
    await page.locator('#mv-freecam-follow').uncheck();

    // The project, its history, the game camera and the export are untouched.
    await setMode(page, 'live');
    await seek(page, time);
    const after = await state(page);
    assert.deepEqual(after.project, before.project, '12035: the project is unchanged');
    assert.deepEqual([after.history.undo, after.history.redo], [0, 0], '12035: no history step');
    assert.deepEqual(await camera(page), gameBefore, '12035: the game camera is untouched');
    const exportedAfter = await exportTimeline();
    assert(exportedAfter.equals(exportedBefore), '12035: the native timeline export is byte-identical');
    assert.deepEqual(errors, []);
    await page.context().close();
    return { member: label, views, exportBytes: exportedAfter.length };
  } finally {
    server.child.kill();
  }
}

async function run() {
  let browser, server;
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const result = await synthetic(browser, server.url);
    const layout = await layouts(browser, server.url);
    const realResult = await real(browser);
    console.log(JSON.stringify({ status: 'PASS', evidence, synthetic: result, layout, real: realResult }));
  } finally {
    if (browser) await browser.close();
    if (server) server.processHandle.kill();
    fs.rmSync(library, { recursive: true, force: true });
    if (ownEvidence && process.exitCode === undefined) fs.rmSync(evidence, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
