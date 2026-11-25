/* MV Studio layout in the real workbench with the 12035 timeline structure
   (tests/fixtures/mv_studio_tracks_12035.json) on a local stage GLB: the stage's share of
   the screen at 1366x768 and on phones (portrait and landscape), the compact toolbar with
   named icon buttons, and the stage / side panel splitter — pointer drag (at most one
   redraw per animation frame, the drawing buffer and the camera aspect follow the stage
   on every frame), the keyboard (arrows, Shift, Home, End, Enter, Escape), double click,
   folding the panel away and back, the toolbar toggle, the values kept across a reload,
   and the stacked phone layout where the splitter sets the panel height. Where taps land on
   touch screens: controls beside the splitter (stage overlay controls at their 8 px inset,
   the side panel's fields) keep their whole box. Korean UI, with screenshots in
   EVIDENCE_DIR. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-layout-library-'));
const modded = path.join(library, 'modded');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-layout-browser-'));
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, 'stage-fixture.glb'), fixture().glb);

const WIDTH_KEY = 'elichika.mv.inspectorWidth.v1', HEIGHT_KEY = 'elichika.mv.inspectorHeight.v1';
const FOLDED_KEY = 'elichika.mv.inspectorCollapsed.v1';

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

// The workbench process ends before its library folder is removed.
function stopped(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) return resolve();
    child.once('exit', () => resolve());
    child.kill();
  });
}

// Keeps the scene the editor creates (its camera lenses) and counts WebGL draw calls per
// animation frame. Runs before the page scripts.
function probe() {
  const box = window.mvLayoutProbe = { scene: null, draws: 0, frames: [] };
  let factory;
  Object.defineProperty(window, 'MVStudioScene', {
    configurable: true,
    get() { return factory; },
    set(value) { factory = { ...value, create(...options) { return (box.scene = value.create(...options)); } }; },
  });
  for (const proto of [window.WebGL2RenderingContext?.prototype, window.WebGLRenderingContext?.prototype]) {
    if (!proto) continue;
    for (const name of ['drawElements', 'drawArrays', 'drawElementsInstanced', 'drawArraysInstanced']) {
      const original = proto[name];
      if (typeof original !== 'function') continue;
      proto[name] = function (...args) { box.draws++; return original.apply(this, args); };
    }
  }
}

// The 12035 structure on the local stage model (one member wearing the same model).
function project(local) {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'mv_studio_tracks_12035.json'), 'utf8'));
  for (const track of data.tracks) delete track.editableValues;
  return { ...local, name: 'Timeline 12035', duration: data.duration, nativeTimeline: true, tracks: data.tracks,
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12035, assetId: 1 },
    performers: [{ id: 'member-1', label: '우에하라 아유무', position: 1, glb: local.stage.glb, transform: { position: [0, 0, 0] } }],
    quality: { mode: 1, modes: [{ id: 1, label: 'Medium', values: {} }], options: [], values: {} } };
}

// embedded: the page as the Android and macOS apps show it (no workbench header).
async function openProject(page, url, embedded = false) {
  await page.goto(url + (embedded ? '/?embedded=1#mv' : '/#mv'));
  await page.waitForFunction(() => MVStudio.getState().visible);
  await page.locator('#mv-open').click();
  await page.waitForFunction((folder) => document.getElementById('picker-crumb').textContent === folder, modded);
  await page.locator('#picker-entries li').filter({ hasText: 'stage-fixture.glb' }).click();
  await page.waitForFunction(() => !!MVStudio.getState().project?.stage?.glb);
  const local = (await page.evaluate(() => MVStudio.getState())).project;
  const timeline = project(local);
  await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
    regions: [{ id: 'gl', label: 'Global (GL)' }], platforms: [{ id: 'android', label: 'Android' }],
    songs: [{ id: 12035, title: 'Timeline 12035', variants: [{ id: 1, label: 'MV' }] }] } }));
  await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: timeline }));
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
  await page.locator('#mv-game-load').click();
  await page.waitForFunction(() => MVStudio.getState().project?.name === 'Timeline 12035' && !document.querySelector('#mv-import-game').disabled);
  await page.locator('#mv-timeline-grid .mv-clip').first().waitFor();
  await page.waitForFunction(() => !!document.querySelector('#mv-scene canvas') && !document.getElementById('mv-preview-controls').hidden);
  await settle(page);
}

// Two animation frames: layout, the ResizeObservers and the redraw have run.
const settle = (page) => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));

// The state once the frame after the last change is painted.
async function read(page) {
  await settle(page);
  return page.evaluate(measure);
}

// Where things are and what the renderer draws into.
function measure() {
  const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
  const grip = document.getElementById('mv-inspector-resizer'), inspector = document.getElementById('mv-inspector');
  const mount = document.getElementById('mv-scene'), canvas = mount.querySelector('canvas');
  const scene = window.mvLayoutProbe.scene;
  // After a reload no MV is open: the layout is there, the stage is empty.
  const box = (canvas || mount).getBoundingClientRect();
  const visible = Math.max(0, Math.min(box.right, innerWidth) - Math.max(box.left, 0)) * Math.max(0, Math.min(box.bottom, innerHeight) - Math.max(box.top, 0));
  const storage = (key) => { try { return localStorage.getItem(key); } catch (_) { return 'unavailable'; } };
  const shown = inspector.offsetParent !== null;
  return {
    share: visible / (innerWidth * innerHeight),
    stage: { width: mount.clientWidth, height: mount.clientHeight },
    canvas: canvas && { width: canvas.width, height: canvas.height, cssWidth: canvas.clientWidth, cssHeight: canvas.clientHeight },
    aspect: scene && { view: scene.getViewPose().aspect, game: scene.gameCameraLens().aspect },
    inspector: shown ? { width: Math.round(inspector.getBoundingClientRect().width), height: Math.round(inspector.getBoundingClientRect().height),
      left: inspector.getBoundingClientRect().left, top: inspector.getBoundingClientRect().top } : null,
    preview: rect('.mv-preview').toJSON(), timeline: rect('.mv-timeline').toJSON(), workspace: rect('#mv-workspace').toJSON(),
    toolbar: rect('#tab-mv > .mv-toolbar').height, timelineChrome: rect('#mv-timeline-scroll').top - rect('.mv-timeline').top,
    viewportBottom: innerHeight - parseFloat(getComputedStyle(document.querySelector('main')).paddingBottom),
    pageOverflow: document.documentElement.scrollWidth - innerWidth,
    grip: { hidden: grip.hidden || grip.offsetParent === null, orientation: grip.getAttribute('aria-orientation'),
      width: grip.getBoundingClientRect().width, height: grip.getBoundingClientRect().height,
      now: Number(grip.getAttribute('aria-valuenow')), min: Number(grip.getAttribute('aria-valuemin')), max: Number(grip.getAttribute('aria-valuemax')),
      text: grip.getAttribute('aria-valuetext'), label: document.getElementById(grip.getAttribute('aria-labelledby')).textContent },
    toggle: document.getElementById('mv-inspector-toggle').getAttribute('aria-expanded'),
    folded: document.getElementById('mv-workspace').classList.contains('mv-inspector-collapsed'),
    stored: { width: storage('elichika.mv.inspectorWidth.v1'), height: storage('elichika.mv.inspectorHeight.v1'),
      folded: storage('elichika.mv.inspectorCollapsed.v1') },
  };
}

const near = (actual, expected, label, tolerance = 1) => assert(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} differs from ${expected}`);

// The drawing buffer has the stage's shape (no stretched frame) and both cameras use its aspect.
function assertRenderer(state, label) {
  const { stage, canvas, aspect } = state;
  assert.equal(canvas.cssWidth, stage.width, `${label}: the canvas fills the stage`);
  assert.equal(canvas.cssHeight, stage.height, `${label}: the canvas fills the stage`);
  // three.js floors width × ratio and height × ratio separately: one buffer pixel either way.
  const ratio = canvas.height / stage.height;
  near(canvas.width, stage.width * ratio, `${label}: buffer width for its height`, 1);
  assert.equal(aspect.view, stage.width / stage.height, `${label}: free camera aspect`);
  assert.equal(aspect.game, stage.width / stage.height, `${label}: game camera aspect`);
}

// Where taps land beside the two splitters. span: how far each splitter's target reaches
// across its band (sampled every quarter pixel through its middle). overlay: controls placed
// at the 8 px inset stage overlay controls keep, along the stage edge beside the splitter,
// each probed 1 px inside its corners and edges and at its centre; missed lists the probes
// that reach something else. fields: the same probes on the side panel's fields nearest the
// splitter. bottoms: what a tap 1 px above the bottom of the stage and of the panel reaches
// (never the timeline resizer below them).
function targets() {
  const portrait = matchMedia('(max-width: 640px) and (orientation: portrait)').matches;
  const split = document.getElementById('mv-inspector-resizer'), resizer = document.getElementById('mv-timeline-resizer');
  const preview = document.querySelector('.mv-preview'), inspector = document.getElementById('mv-inspector');
  const span = (element, vertical) => {
    const box = element.getBoundingClientRect();
    if (!box.width || !box.height) return 0;
    const middle = vertical ? box.left + box.width / 2 : box.top + box.height / 2;
    let first = null, last = null;
    for (let at = (vertical ? box.top : box.left) - 40; at <= (vertical ? box.bottom : box.right) + 40; at += .25) {
      const node = vertical ? document.elementFromPoint(middle, at) : document.elementFromPoint(at, middle);
      if (node && element.contains(node)) { first ??= at; last = at; }
    }
    return first === null ? 0 : last - first + .25;
  };
  const name = (node) => !node ? null : node.closest('#mv-inspector-resizer') ? 'splitter' : node.closest('#mv-timeline-resizer') ? 'timeline resizer' : node.id || node.tagName;
  const missed = (control) => {
    const box = control.getBoundingClientRect(), out = [];
    for (const x of [box.left + 1, box.left + box.width / 2, box.right - 1]) {
      for (const y of [box.top + 1, box.top + box.height / 2, box.bottom - 1]) {
        const node = document.elementFromPoint(x, y);
        if (!node || !control.contains(node)) out.push(`${Math.round(x - box.left)},${Math.round(y - box.top)}: ${name(node)}`);
      }
    }
    return out;
  };
  const overlay = {};
  for (const place of portrait ? ['bottom: 8px; left: 8px', 'bottom: 8px; right: 8px'] : ['top: 8px; right: 8px', 'bottom: 8px; right: 8px']) {
    const control = document.createElement('button');
    control.type = 'button';
    control.style.cssText = `position: absolute; ${place}; z-index: 1; width: 32px; height: 32px; min-height: 0; padding: 0; border-radius: 0; box-sizing: border-box`;
    preview.append(control);
    overlay[place] = missed(control);
    control.remove();
  }
  // The panel's fields in view (a tap at their centre reaches them) that start near its
  // edge: a tap 1 px inside their edge beside the splitter reaches them too.
  const panel = inspector.getBoundingClientRect();
  const fields = [...inspector.querySelectorAll('.mv-panel-content :is(input, select, button, label)')].filter((node) => {
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.left - panel.left < 24 && node.contains(document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2));
  });
  const fieldsMissed = portrait ? [] : fields.flatMap((node) => {
    const box = node.getBoundingClientRect(), hit = document.elementFromPoint(box.left + 1, box.top + box.height / 2);
    return node.contains(hit) ? [] : [`${node.id || node.tagName}: ${name(hit)}`];
  });
  const stage = preview.getBoundingClientRect();
  return {
    split: span(split, portrait), timeline: span(resizer, true), overlay, fields: fields.length, fieldsMissed,
    bottoms: { stage: name(document.elementFromPoint(stage.left + stage.width / 2, stage.bottom - 1)),
      panel: panel.height ? name(document.elementFromPoint(panel.left + panel.width / 2, panel.bottom - 1)) : null },
  };
}

async function desktop(browser, url) {
  const context = await browser.newContext({ locale: 'ko', viewport: { width: 1366, height: 768 } });
  await context.addInitScript(probe);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openProject(page, url);
  let state = await read(page);
  await page.screenshot({ path: path.join(evidence, 'layout-1366-ko.png') });

  // ---- The stage's share and the compact frame -------------------------------------------
  assert(state.share >= .33, `the stage takes a third of a 1366x768 screen (${state.share.toFixed(3)})`);
  assert(state.toolbar <= 30, `the MV toolbar is one row (${state.toolbar})`);
  assert(state.timelineChrome <= 80, `the timeline toolbar is compact (${state.timelineChrome})`);
  assert.equal(state.pageOverflow, 0);
  near(state.timeline.bottom, state.viewportBottom, 'the timeline ends at the page bottom');
  // Icon buttons keep their names (accessible name and tooltip) in Korean.
  for (const [id, name] of [['mv-open', '모드 또는 프로젝트 열기'], ['mv-save', 'MV 프로젝트 저장'], ['mv-export-timeline', '게임용 타임라인 내보내기'],
    ['mv-inspector-toggle', '사이드 패널'], ['mv-rewind', '처음으로'], ['mv-frame-scene', '무대 전체 보기']]) {
    const button = page.getByRole('button', { name, exact: true });
    assert.equal(await button.getAttribute('id'), id, `${id} is named ${name}`);
    assert.equal(await button.getAttribute('title'), name, `${id} has a tooltip`);
  }
  assert.equal(await page.locator('#mv-panel-menu > summary').getAttribute('title'), '패널 설정');
  assert.equal(await page.locator('#mv-panel-menu > summary').evaluate((node) => node.textContent.trim()), '패널 설정');
  assert(await page.getByRole('button', { name: '게임에서 MV 불러오기' }).isVisible(), 'the primary action keeps its text');
  assert(await page.locator('#mv-assets').evaluate((node) => !node.open), 'MV assets folds away once an MV is open');

  // ---- Splitter: the default and its range ----------------------------------------------
  const grip = page.getByRole('separator', { name: '패널 너비' });
  assert.equal(state.grip.orientation, 'vertical');
  assert.equal(state.grip.label, '패널 너비');
  const room = state.workspace.width;
  assert.equal(state.grip.min, 0);
  assert.equal(state.grip.max, Math.min(Math.round(room * .6), Math.floor(room - 6 - 320)));
  near(state.inspector.width, Math.min(360, Math.max(240, 1366 * .24)), 'default side panel width');
  assert.equal(state.grip.now, state.inspector.width);
  assert.equal(state.grip.text, `${state.inspector.width} px`);
  assert(state.preview.right < state.inspector.left && state.preview.top === state.inspector.top, 'stage | splitter | panel');
  assert.equal(state.timeline.left, state.preview.left);
  assertRenderer(state, 'default');
  const initial = state;
  // The stage's overlay controls and the panel's fields beside the splitter stay whole.
  let taps = await page.evaluate(targets);
  assert.deepEqual(taps.overlay, { 'top: 8px; right: 8px': [], 'bottom: 8px; right: 8px': [] }, 'stage overlay controls beside the splitter');
  assert(taps.fields > 0, 'panel fields beside the splitter');
  assert.deepEqual(taps.fieldsMissed, [], 'panel fields beside the splitter');

  // ---- Pointer drag: the panel follows; one redraw per frame at most; no stretched frame --
  const box = await grip.boundingBox();
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  // One redraw draws this many times (the stage, shadows and post passes); two redraws
  // in one frame would draw about twice as many.
  const perRender = await page.evaluate(() => {
    const probe = window.mvLayoutProbe, before = probe.draws;
    probe.scene.resize();
    return probe.draws - before;
  });
  assert(perRender > 0, 'a redraw draws');
  await page.evaluate(() => {
    const probe = window.mvLayoutProbe;
    probe.frames = [];
    probe.sampling = true;
    let last = probe.draws;
    const sample = () => {
      if (!probe.sampling) return;
      const mount = document.getElementById('mv-scene'), canvas = mount.querySelector('canvas');
      probe.frames.push({ draws: probe.draws - last, width: mount.clientWidth, height: mount.clientHeight,
        buffer: [canvas.width, canvas.height], view: probe.scene.getViewPose().aspect, game: probe.scene.gameCameraLens().aspect });
      last = probe.draws;
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let step = 1; step <= 12; step++) await page.mouse.move(x - step * 10, y);
  await page.mouse.up();
  await settle(page);
  const frames = await page.evaluate(() => { window.mvLayoutProbe.sampling = false; return window.mvLayoutProbe.frames; });
  state = await read(page);
  near(state.inspector.width, initial.inspector.width + 120, 'dragged 120 px to the left');
  near(state.stage.width, initial.stage.width - 120, 'the stage gave the room');
  assert.equal(state.stored.width, String(state.inspector.width), 'the width is kept');
  assertRenderer(state, 'after the drag');
  const drawn = frames.filter((frame) => frame.draws > 0);
  assert(drawn.length > 0, 'the drag redraws the stage');
  assert(frames.every((frame) => frame.draws < perRender * 1.5), `at most one redraw per animation frame (${frames.map((frame) => frame.draws).join(',')} / ${perRender})`);
  for (const frame of frames) {
    // Sampled at the start of a frame: what was drawn last has this frame's stage shape.
    assert.equal(frame.view, frame.width / frame.height, 'free camera aspect follows the stage on every frame');
    assert.equal(frame.game, frame.width / frame.height, 'game camera aspect follows the stage on every frame');
    near(frame.buffer[0], frame.width * frame.buffer[1] / frame.height, 'buffer shape follows the stage on every frame');
  }
  // Many pointer moves inside one frame: one apply, one redraw.
  const burst = await page.evaluate(async () => {
    const probe = window.mvLayoutProbe, grip = document.getElementById('mv-inspector-resizer');
    const box = grip.getBoundingClientRect(), x = box.left + box.width / 2, y = box.top + box.height / 2;
    const fire = (type, dx) => grip.dispatchEvent(new PointerEvent(type, { pointerId: 7, isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1,
      clientX: x + dx, clientY: y, bubbles: true, cancelable: true }));
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const before = probe.draws;
    fire('pointerdown', 0);
    for (let step = 1; step <= 8; step++) fire('pointermove', step * 4);
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const draws = probe.draws - before;
    fire('pointerup', 32);
    return draws;
  });
  assert(burst > 0 && burst < perRender * 1.5, `eight moves in one frame redraw once (${burst} / ${perRender})`);
  state = await read(page);
  near(state.inspector.width, initial.inspector.width + 120 - 32, 'the burst moved the splitter 32 px right');

  // ---- Keyboard --------------------------------------------------------------------------
  await grip.focus();
  assert(await grip.evaluate((node) => node.matches(':focus-visible') || document.activeElement === node));
  let width = (await read(page)).inspector.width;
  await grip.press('ArrowLeft');
  assert.equal((await read(page)).inspector.width, width + 16, 'Left widens the panel by 16 px');
  await grip.press('Shift+ArrowLeft');
  assert.equal((await read(page)).inspector.width, width + 16 + 64, 'Shift+Left by 64 px');
  await grip.press('ArrowRight');
  await grip.press('ArrowRight');
  state = await read(page);
  assert.equal(state.inspector.width, width + 48);
  assert.equal(state.grip.now, width + 48);
  assertRenderer(state, 'after the arrow keys');
  await grip.press('End');
  state = await read(page);
  assert.equal(state.inspector.width, state.grip.max, 'End: the panel at its largest');
  assert(state.stage.width >= 320, 'the stage keeps its minimum');
  assertRenderer(state, 'End');
  for (let count = 0; count < 40; count++) await grip.press('Shift+ArrowRight');
  state = await read(page);
  assert.equal(state.inspector.width, 220, 'arrows stop at the minimum width');
  assert.equal(state.folded, false, 'arrows never fold the panel away');
  await grip.press('Home');
  state = await read(page);
  assert.equal(state.inspector.width, initial.inspector.width, 'Home: the default width');
  assert.equal(state.stored.width, null, 'the default is not stored');

  // Enter folds the panel away and brings it back; the stage takes the room.
  await grip.press('Enter');
  state = await read(page);
  assert.equal(state.inspector, null, 'Enter hides the panel');
  assert.equal(state.folded, true);
  assert.equal(state.grip.now, 0);
  assert.equal(state.grip.text, '숨김');
  assert.equal(state.toggle, 'false');
  assert.equal(state.stored.folded, '1');
  assert(!state.grip.hidden, 'the splitter stays to bring the panel back');
  assert(state.grip.width <= 9, `a thin rail (${state.grip.width})`);
  near(state.stage.width, state.workspace.width - state.grip.width, 'the stage spans the row beside the rail');
  assertRenderer(state, 'folded');
  taps = await page.evaluate(targets);
  assert.deepEqual(taps.overlay, { 'top: 8px; right: 8px': [], 'bottom: 8px; right: 8px': [] }, 'stage overlay controls beside the rail');
  await page.screenshot({ path: path.join(evidence, 'layout-1366-folded-ko.png') });
  await grip.press('ArrowRight');
  assert.equal((await read(page)).folded, true, 'the shrinking arrow leaves it folded');
  await grip.press('ArrowLeft');
  state = await read(page);
  assert.equal(state.folded, false, 'the growing arrow brings it back');
  assert.equal(state.inspector.width, initial.inspector.width);
  await grip.press('Enter');
  await grip.press('Enter');
  state = await read(page);
  assert.equal(state.folded, false);
  assert.equal(state.stored.folded, null);

  // The toolbar toggle does the same without a keyboard.
  const toggle = page.getByRole('button', { name: '사이드 패널' });
  await toggle.click();
  state = await read(page);
  assert.equal(state.folded, true);
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
  await toggle.click();
  assert.equal((await read(page)).folded, false);

  // A drag below half the minimum folds the panel; dragging out brings it back at the minimum.
  let grab = await grip.boundingBox();
  await page.mouse.move(grab.x + grab.width / 2, grab.y + grab.height / 2);
  await page.mouse.down();
  await page.mouse.move(grab.x + grab.width / 2 + initial.inspector.width - 100, grab.y + grab.height / 2, { steps: 6 });
  await page.mouse.up();
  state = await read(page);
  assert.equal(state.folded, true, 'dragged past half the minimum: folded');
  assertRenderer(state, 'folded by a drag');
  grab = await grip.boundingBox();
  await page.mouse.move(grab.x + grab.width / 2, grab.y + grab.height / 2);
  await page.mouse.down();
  await page.mouse.move(grab.x + grab.width / 2 - 150, grab.y + grab.height / 2, { steps: 6 });
  await page.mouse.up();
  state = await read(page);
  assert.equal(state.folded, false, 'dragged back out');
  assert.equal(state.inspector.width, 220, 'at the minimum width');

  // Escape during a drag puts the panel back.
  grab = await grip.boundingBox();
  await page.mouse.move(grab.x + grab.width / 2, grab.y + grab.height / 2);
  await page.mouse.down();
  await page.mouse.move(grab.x + grab.width / 2 - 90, grab.y + grab.height / 2, { steps: 4 });
  await settle(page);
  assert.equal((await read(page)).inspector.width, 310);
  await page.keyboard.press('Escape');
  await page.mouse.up();
  state = await read(page);
  assert.equal(state.inspector.width, 220, 'Escape restores the width the drag started from');

  // Double click: the default again.
  grab = await grip.boundingBox();
  await page.mouse.dblclick(grab.x + grab.width / 2, grab.y + grab.height / 2);
  state = await read(page);
  assert.equal(state.inspector.width, initial.inspector.width, 'double click restores the default');
  assert.equal(state.stored.width, null);

  // ---- Kept across a reload ---------------------------------------------------------------
  await grip.focus();
  await grip.press('Shift+ArrowLeft');
  await grip.press('Shift+ArrowLeft');
  const kept = (await read(page)).inspector.width;
  assert.equal(kept, initial.inspector.width + 128);
  await page.reload();
  await page.waitForFunction(() => MVStudio.getState().visible);
  await settle(page);
  state = await read(page);
  assert.equal(state.inspector.width, kept, 'the width survives a reload');
  await page.getByRole('separator', { name: '패널 너비' }).press('Enter');
  await page.reload();
  await page.waitForFunction(() => MVStudio.getState().visible);
  await settle(page);
  state = await read(page);
  assert.equal(state.folded, true, 'so does the folded panel');
  assert.equal(state.toggle, 'false');
  await page.getByRole('button', { name: '사이드 패널' }).click();
  assert.equal((await read(page)).inspector.width, kept);
  // A stored width the window cannot hold is clamped, not overwritten.
  await page.evaluate((key) => localStorage.setItem(key, '1500'), WIDTH_KEY);
  await page.reload();
  await page.waitForFunction(() => MVStudio.getState().visible);
  await settle(page);
  state = await read(page);
  assert.equal(state.inspector.width, state.grip.max, 'clamped to the room there is');
  assert.equal(state.stored.width, '1500');
  await page.evaluate((key) => localStorage.setItem(key, 'wide'), WIDTH_KEY);
  await page.reload();
  await page.waitForFunction(() => MVStudio.getState().visible);
  await settle(page);
  assert.equal((await read(page)).inspector.width, initial.inspector.width, 'a malformed value is ignored');
  // Without storage (private windows, blocked site data) the splitter still works.
  await page.evaluate(() => {
    for (const name of ['getItem', 'setItem', 'removeItem']) Storage.prototype[name] = () => { throw new Error('blocked'); };
  });
  await page.getByRole('separator', { name: '패널 너비' }).press('ArrowLeft');
  assert.equal((await read(page)).inspector.width, initial.inspector.width + 16);

  assert.deepEqual(errors, []);
  await context.close();
}

async function phonePortrait(browser, url) {
  const context = await browser.newContext({ locale: 'ko', viewport: { width: 412, height: 915 }, isMobile: true, hasTouch: true });
  await context.addInitScript(probe);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openProject(page, url, true);
  let state = await read(page);
  await page.screenshot({ path: path.join(evidence, 'layout-phone-portrait-ko.png') });
  assert(state.share >= .22, `the stage takes over a fifth of a portrait phone (${state.share.toFixed(3)})`);
  assert(state.toolbar <= 38, `the MV toolbar is one row on a phone (${state.toolbar})`);
  assert.equal(state.pageOverflow, 0);
  near(state.timeline.bottom, state.viewportBottom, 'the timeline ends at the page bottom');
  // Touch targets stay usable (boxes have a 32 px row as their target).
  const small = await page.evaluate(() => [...document.querySelectorAll('#tab-mv :is(button, select, summary, input:not([type=range], [type=checkbox]))')]
    .filter((node) => node.offsetParent !== null && !node.closest('#mv-timeline-grid'))
    .map((node) => { const box = node.getBoundingClientRect(); return `${node.id || node.className || node.tagName} ${Math.round(box.width)}x${Math.round(box.height)}`; })
    .filter((text) => text.split(' ').pop().split('x').some((size) => Number(size) < 32)));
  assert.deepEqual(small, [], 'no touch target under 32 px');
  // The stage's overlay controls along its bottom edge (above the splitter) stay whole.
  const taps = await page.evaluate(targets);
  assert.deepEqual(taps.overlay, { 'bottom: 8px; left: 8px': [], 'bottom: 8px; right: 8px': [] }, 'stage overlay controls above the splitter');

  // The panel sits under the stage; the same splitter, now horizontal, sets its height.
  const grip = page.getByRole('separator', { name: '패널 높이' });
  assert.equal(state.grip.orientation, 'horizontal');
  assert(state.inspector.top > state.preview.bottom, 'the panel is under the stage');
  assert(state.timeline.top > state.inspector.top + state.inspector.height, 'and above the timeline');
  const initial = state;
  await grip.press('ArrowUp');
  state = await read(page);
  assert.equal(state.inspector.height, initial.inspector.height + 16, 'Up makes the panel taller');
  near(state.stage.height, initial.stage.height - 16, 'the stage gave the room');
  assertRenderer(state, 'portrait, Up');
  assert.equal(state.stored.height, String(state.inspector.height));
  assert.equal(state.stored.width, null, 'the width is a separate preference');
  // A touch drag downward.
  const box = await grip.boundingBox();
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  assert.equal((await read(page)).inspector.height, initial.inspector.height + 16, 'a tap does not move it');
  const drag = await page.evaluate(async () => {
    const grip = document.getElementById('mv-inspector-resizer'), box = grip.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const fire = (type, dy) => grip.dispatchEvent(new PointerEvent(type, { pointerId: 3, pointerType: 'touch', isPrimary: true, button: 0,
      buttons: type === 'pointerup' ? 0 : 1, clientX: x, clientY: y + dy, bubbles: true, cancelable: true }));
    fire('pointerdown', 0);
    for (let step = 1; step <= 5; step++) {
      fire('pointermove', step * 8);
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    fire('pointerup', 40);
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return document.getElementById('mv-inspector').getBoundingClientRect().height;
  });
  near(drag, initial.inspector.height + 16 - 40, 'dragged 40 px down');
  await grip.press('End');
  state = await read(page);
  assert.equal(state.inspector.height, state.grip.max, 'End: the tallest panel');
  near(state.stage.height, 108, 'the stage keeps its minimum height');
  near(state.timeline.bottom, state.viewportBottom, 'the timeline still fits');
  assertRenderer(state, 'portrait, End');
  // Folded: a labelled bar under the stage brings the panel back with a tap.
  await grip.press('Enter');
  state = await read(page);
  assert.equal(state.inspector, null);
  assert(state.share > initial.share, 'the stage takes the panel\'s room');
  assertRenderer(state, 'portrait, folded');
  const reopen = page.locator('#mv-inspector-resizer .mv-inspector-reopen');
  assert(await reopen.isVisible(), 'the folded bar is labelled');
  assert.equal((await reopen.textContent()).replace(/\s+/g, ' ').trim(), '▴사이드 패널');
  await page.screenshot({ path: path.join(evidence, 'layout-phone-portrait-folded-ko.png') });
  const bar = await reopen.boundingBox();
  assert(bar.height >= 32, `the folded bar is a touch target (${bar.height})`);
  await page.touchscreen.tap(bar.x + bar.width / 2, bar.y + bar.height / 2);
  state = await read(page);
  assert.equal(state.folded, false, 'a tap brings the panel back');
  await grip.press('Home');
  state = await read(page);
  near(state.inspector.height, initial.inspector.height, 'Home: the default height');
  assert.equal(state.stored.height, null);

  assert.deepEqual(errors, []);
  await context.close();
}

// A touch tablet held upright (820x1180, side by side): the splitter's target leaves the
// stage's overlay controls and the panel's fields whole, and the folded rail.
async function tablet(browser, url) {
  const context = await browser.newContext({ locale: 'ko', viewport: { width: 820, height: 1180 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  await context.addInitScript(probe);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openProject(page, url, true);
  let state = await read(page);
  assert.equal(state.grip.orientation, 'vertical');
  assert.equal(state.inspector.width, 240, 'the touch minimum width');
  assert.equal(state.pageOverflow, 0);
  const band = state.grip.width;
  let taps = await page.evaluate(targets);
  assert.deepEqual(taps.overlay, { 'top: 8px; right: 8px': [], 'bottom: 8px; right: 8px': [] }, 'stage overlay controls beside the splitter');
  assert(taps.fields > 0, 'panel fields beside the splitter');
  assert.deepEqual(taps.fieldsMissed, [], 'panel fields beside the splitter');
  await page.screenshot({ path: path.join(evidence, 'layout-tablet-ko.png') });

  const grip = page.getByRole('separator', { name: '패널 너비' });
  await grip.press('Enter');
  state = await read(page);
  assert.equal(state.folded, true);
  near(state.stage.width, state.workspace.width - state.grip.width, 'folded: the stage spans the row beside the rail');
  assert.equal(state.pageOverflow, 0, 'the folded rail stays inside the page');
  taps = await page.evaluate(targets);
  assert.deepEqual(taps.overlay, { 'top: 8px; right: 8px': [], 'bottom: 8px; right: 8px': [] }, 'overlay controls beside the rail');
  await page.screenshot({ path: path.join(evidence, 'layout-tablet-folded-ko.png') });
  await grip.press('Enter');
  await grip.press('Home');
  assert.equal((await read(page)).inspector.width, 240);
  assert.deepEqual(errors, []);
  await context.close();
}

async function phoneLandscape(browser, url) {
  const context = await browser.newContext({ locale: 'ko', viewport: { width: 915, height: 412 }, isMobile: true, hasTouch: true });
  await context.addInitScript(probe);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openProject(page, url, true);
  const state = await read(page);
  await page.screenshot({ path: path.join(evidence, 'layout-phone-landscape-ko.png') });
  assert(state.share >= .24, `the stage takes about a quarter of a landscape phone (${state.share.toFixed(3)})`);
  assert.equal(state.pageOverflow, 0);
  near(state.timeline.bottom, state.viewportBottom, 'the timeline ends at the page bottom');
  assert.equal(state.grip.orientation, 'vertical');
  assert.equal(state.inspector.width, 240, 'the touch minimum width');
  assertRenderer(state, 'landscape');
  const taps = await page.evaluate(targets);
  assert.deepEqual(taps.overlay, { 'top: 8px; right: 8px': [], 'bottom: 8px; right: 8px': [] }, 'stage overlay controls beside the splitter');
  assert.deepEqual(taps.fieldsMissed, [], 'panel fields beside the splitter');
  const grip = page.getByRole('separator', { name: '패널 너비' });
  await grip.press('Shift+ArrowLeft');
  assert.equal((await read(page)).inspector.width, Math.min(240 + 64, state.grip.max));
  assertRenderer(await read(page), 'landscape, wider');
  assert.deepEqual(errors, []);
  await context.close();
}

async function run() {
  let server, browser;
  try {
    server = await startServer();
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    await desktop(browser, server.url);
    await tablet(browser, server.url);
    await phonePortrait(browser, server.url);
    await phoneLandscape(browser, server.url);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    if (server) await stopped(server.processHandle);
    fs.rmSync(library, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
