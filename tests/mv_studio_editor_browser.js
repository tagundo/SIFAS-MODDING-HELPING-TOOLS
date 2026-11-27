/* MV Studio editor in the real workbench: timeline category tabs on the 12035
   timeline structure (tests/fixtures/mv_studio_tracks_12035.json), the member chips
   and track-name search, tab memory per session, the Edit tab, undo/redo by
   keyboard and buttons, clip name edits, a clip drag, edits kept across a
   costume re-import, the inert tablist during a game import, and the
   no-regression rule: an opened project stays deep-equal to its input until the
   first edit. Korean UI, with screenshots in EVIDENCE_DIR. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
require('../webtools/web/static/mv-studio-timeline-interact.js');
const Interact = globalThis.MVStudioTimelineInteract;

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-editor-library-'));
const modded = path.join(library, 'modded');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-editor-browser-'));
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, 'stage-fixture.glb'), fixture().glb);

// The 12035 structure with placeholder values for every editable value key.
function timeline({ duet = false } = {}) {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'mv_studio_tracks_12035.json'), 'utf8'));
  const placeholder = (key) => /color/i.test(key) ? { r: 1, g: .8, b: .6, a: 1 }
    : ['direction', 'center', 'offset'].includes(key) ? { x: 0, y: 0, z: 0 }
      : key === 'paramName' ? 'a' : key === 'keyframes' ? undefined
        : ['index', 'target', 'cheekType'].includes(key) ? 1 : .5;
  for (const track of data.tracks) {
    for (const event of track.events) {
      if (!event.editableValues && track.editableValues) event.editableValues = track.editableValues.slice();
      for (const key of event.editableValues || []) {
        const value = placeholder(key);
        if (!(key in event.values) && value !== undefined) event.values[key] = value;
      }
    }
    delete track.editableValues;
  }
  // Member1/LipSync keeps the Unity editor's overlap blends, as every stock lip-sync track does.
  const lips = data.tracks.find((track) => track.label === 'Member1/LipSync');
  const blends = Interact.blendTimes(lips.events);
  for (const event of lips.events) Object.assign(event.values, blends.get(event.id));
  // Playable classes for the timing-field rules: the camera shots and the flash lights.
  for (const [label, playableClass] of [['CameraMotion/Camera1', 'AnimationPlayableAsset'],
    ['StageEffect/Expert/Flash Light/Live Flash Light Track', 'LiveFlashLightClip']]) {
    for (const event of data.tracks.find((track) => track.label === label).events) {
      Object.assign(event.values, { playableClass, clipIn: 0, timeScale: 1 });
    }
  }
  if (duet) {
    // A second member: copies of the Member1 lip-sync and eye tracks bound to Member2.
    for (const label of ['Member1/Eye', 'Member1/LipSync']) {
      const index = data.tracks.findIndex((track) => track.label === label);
      const copy = JSON.parse(JSON.stringify(data.tracks[index]));
      copy.id += 'm2';
      copy.label = label.replace('Member1', 'Member2');
      copy.binding = copy.binding.replace('Member1', 'Member2');
      for (const event of copy.events) event.id = event.id.replace(/^[^:]+/, copy.id);
      data.tracks.splice(index + 1, 0, copy);
    }
  }
  return data;
}

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

async function chooseFile(page, folder, file) {
  await page.waitForFunction((expected) => document.getElementById('picker-crumb').textContent === expected, folder);
  await page.locator('#picker-entries li').filter({ hasText: file }).click();
}

const state = (page) => page.evaluate(() => MVStudio.getState());
const tabState = (page) => page.evaluate(() => [...document.querySelectorAll('#mv-timeline-tabs [role=tab]')].map((tab) => ({
  id: tab.dataset.mvTab, text: tab.firstChild.textContent.trim(), count: Number(tab.querySelector('.mv-tab-count').textContent),
  selected: tab.getAttribute('aria-selected') === 'true', tabIndex: tab.tabIndex })));
const laneTabs = (page) => page.evaluate(() => [...document.querySelectorAll('#mv-timeline-grid .mv-lane[data-track]')].map((lane) => lane.dataset.tab));
const laneLabels = (page) => page.evaluate(() => [...document.querySelectorAll('#mv-timeline-grid .mv-lane-label[data-track]:not(.mv-lane-group)')]
  .map((label) => label.textContent));
const findEvent = (project, id) => project.tracks.flatMap((track) => track.events).find((event) => event.id === id);
const findTrack = (project, id) => project.tracks.find((track) => track.id === id);
const editCount = async (page) => Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent());

/* The plugin host contract lanes B, C and D build on (spec §2): a probe plugin
   registered before the page scripts records every hook it receives, and its value
   controls (a colour swatch, a slider) check the gesture rules of spec §6.1. The
   probe project is non-native, so clips can also be duplicated and deleted. */
async function pluginContract(browser, url) {
  const page = await browser.newPage({ locale: 'ko', viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    const calls = [];
    window.probeCalls = calls;
    (window.MVStudioPlugins ||= []).push({
      id: 'probe', order: 5,
      attach(ctx) {
        calls.push('attach');
        window.probeCtx = ctx;
        window.probeEmpty = { project: ctx.project(), selection: ctx.selection(), editor: ctx.editor(true), edited: ctx.edited('x'),
          duration: ctx.duration(), locked: ctx.locked(), tab: ctx.activeTab(), snap: ctx.snap(1.004), frameRate: ctx.frameRate };
        ctx.seek(3);
        ctx.select('a', 'b');
        ctx.refreshLane('a');
        ctx.renderTimeline();
      },
      panels: [{ key: 'probe', name: 'Probe panel', open: true, available: (ctx) => !!ctx.project(),
        render(box, ctx) { box.replaceChildren(ctx.make('p', 'probe ' + ctx.project().name, { id: 'probe-panel-text' })); } }],
      projectChanged(ctx, info) { calls.push('project:' + info.reason + (info.direction ? ':' + info.direction : '')); },
      timeChanged(ctx, time, info) { window.probeTime = { time, playing: info.playing }; },
      selectionChanged(ctx, selection) { calls.push('select:' + (selection ? selection.event.id : 'none')); },
      valueControl(ctx, info) {
        if (info.key === 'paramName') return null;
        if (info.key === 'tint') {
          // Spec §6.1 colour swatch: begin on pointerdown, the picker writes on input
          // after the release, end on change.
          const hex = (colour) => '#' + [colour.r, colour.g, colour.b].map((part) => Math.round(part * 255).toString(16).padStart(2, '0')).join('');
          const swatch = ctx.make('input', null, { type: 'color', 'data-mv-field': 'tint', id: 'probe-tint' });
          swatch.value = hex(info.value);
          swatch.addEventListener('pointerdown', () => { info.gesture.begin(); window.probeTintGesture = info.gesture; });
          swatch.addEventListener('input', () => {
            const rgb = parseInt(swatch.value.slice(1), 16);
            info.set({ r: (rgb >> 16 & 255) / 255, g: (rgb >> 8 & 255) / 255, b: (rgb & 255) / 255, a: 1 });
          });
          swatch.addEventListener('change', () => info.gesture.end());
          return ctx.field('Probe tint', swatch);
        }
        if (info.key === 'intensity') {
          // A slider in a ctx.history gesture, with history.end given straight to the listener.
          const range = ctx.make('input', null, { type: 'range', min: 0, max: 1, step: .01, 'data-mv-field': 'intensity', id: 'probe-intensity' });
          range.value = info.value;
          range.addEventListener('pointerdown', () => ctx.history.begin('Edit value'));
          range.addEventListener('input', () => info.set(Number(range.value)));
          range.addEventListener('change', ctx.history.end);
          return ctx.field('Probe intensity', range);
        }
        if (info.key !== 'weight') return undefined;
        window.probeInfo = { key: info.key, path: info.path, value: info.value, writable: info.writable, original: info.original };
        window.probeGesture = info.gesture;
        const input = ctx.make('input', null, { type: 'number', step: 'any', 'data-mv-field': 'weight', id: 'probe-weight' });
        input.value = info.value;
        input.addEventListener('change', () => info.set(Number(input.value)));
        return ctx.field('Probe weight', input);
      },
      eventHeader(ctx, { event }) { return ctx.make('p', 'header ' + event.id, { id: 'probe-header' }); },
      eventFooter() { return window.probeCtx.make('p', 'footer', { id: 'probe-footer' }); },
      laneDecorate(ctx, track, lane, layout) { lane.dataset.probe = `${layout.rowOf.size}:${layout.rowHeight}:${layout.laneLeft}`; },
      extraLanes(ctx, tab) {
        if (!['camera', 'edit', 'all'].includes(tab)) return [];
        return [{ id: 'probe-rigs', after: 'camera', label: 'Camera rigs (editor)', title: 'Rigs are baked into the shots.',
          render(lane, layout) {
            const range = window.probeRigRange ||= { start: 2, end: 4 };
            const clip = ctx.make('button', 'rig', { type: 'button', class: 'mv-rig-clip', id: 'probe-rig' });
            clip.style.left = `${range.start * layout.pixelsPerSecond}px`;
            clip.style.width = `${(range.end - range.start) * layout.pixelsPerSecond}px`;
            lane.append(clip);
            // Lane D reuses the clip drag: scale and bounds come from ctx.attachDrag.
            ctx.attachDrag(clip, { label: 'Move rig', edges: { start: true, end: true }, snapTargets: () => ctx.snapTargets(),
              getRange: () => ({ ...window.probeRigRange }),
              setRange: (next, info) => {
                if (info.phase !== 'commit') return;
                window.probeRigRange = next;
                (window.probeRigCommits ||= []).push(info.mode);
              } });
          } }];
      },
      clipConstraints(ctx, track) { return track.id === 'camera' ? { resize: false, reason: 'Probe lock' } : undefined; },
      revertEvent(ctx, track, event) { if (event.id !== 'cam-1') return false; calls.push('revert:' + event.id); return true; },
      editedCount(ctx) { return ctx.project() && !window.probeNoEdits ? 2 : 0; },
      keydown(ctx, event) {
        if (event.key === 'j') {   // a plugin key that writes through ctx.history directly
          ctx.history.apply({ label: 'Edit value', detail: 'weight', changes: [{ target: { kind: 'event', track: 'mouth', event: 'lip-1' }, path: ['values', 'weight'], after: .9 }] });
          return true;
        }
        if (event.key !== 'k') return false;
        calls.push('key:k');
        return true;
      },
      beforeSave() { if (window.probeRefuseSave) throw new Error('Probe refuses to save'); },
    });
  });
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  assert.deepEqual(await page.evaluate(() => window.probeEmpty), { project: null, selection: null, editor: null, edited: false,
    duration: 0, locked: false, tab: 'all', snap: 1, frameRate: 60 }, 'ctx is safe without a project');
  assert.deepEqual(await page.evaluate(() => window.probeCalls), ['attach']);
  assert.equal(await page.evaluate(() => document.getElementById('mv-events').nextElementSibling.id), 'mv-panel-probe');
  assert(await page.locator('#mv-panel-probe').isHidden(), 'not available without a project');
  const project = { version: 1, name: 'Probe MV', duration: 20, nativeTimeline: false, assets: [], warnings: [], quality: {},
    performers: [{ id: 'member-1', label: '우에하라 아유무', position: 1, transform: { position: [0, 0, 0] } }],
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 99, assetId: 1 },
    tracks: [
      { id: 'camera', kind: 'camera', binding: 'MainCamera', label: 'Camera', events: [
        { id: 'cam-1', label: 'Shot 1', start: 0, duration: 4, values: { fov: 30 }, editableValues: ['fov'] },
        { id: 'cam-2', label: 'Shot 2', start: 4, duration: 4, values: { fov: 40 }, editableValues: ['fov'] }] },
      { id: 'mouth', kind: 'mouth', binding: '/EntryPoint/Live/Members/Member1', label: 'Member1/LipSync', events: [
        { id: 'lip-1', label: 'A', start: 1, duration: 1, values: { weight: .5, paramName: 'a', tint: { r: 1, g: .4, b: .2, a: 1 }, intensity: .2 },
          editableValues: ['weight', 'paramName', 'tint', 'intensity'] }] }] };
  await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
    regions: [{ id: 'gl', label: 'GL' }], platforms: [{ id: 'android', label: 'Android' }],
    songs: [{ id: 99, title: 'Probe MV', variants: [{ id: 1, label: 'MV' }] }] } }));
  await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: project }));
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
  await page.locator('#mv-game-load').click();
  await page.locator('.mv-clip[data-event=cam-1]').waitFor();
  assert.deepEqual(await page.evaluate(() => window.probeCalls), ['attach', 'project:load']);
  assert.equal(await page.locator('#probe-panel-text').textContent(), 'probe Probe MV');
  assert(await page.locator('#mv-panel-probe').isVisible());
  await page.locator('#mv-panel-menu summary').click();
  assert.equal(await page.locator('[data-mv-panel-option=probe]').count(), 1, 'plugin panels are listed in the panel menu');
  await page.locator('#mv-panel-menu summary').click();
  assert.equal(Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent()), 2, 'editedCount adds to the Edit tab');
  // The clip row height is the lane's --mv-clip-row-height: 24 px with a fine pointer.
  const rowHeight = await page.locator('.mv-lane[data-track=camera]').evaluate((lane) => parseFloat(getComputedStyle(lane).getPropertyValue('--mv-clip-row-height')));
  assert.equal(rowHeight, 24);
  assert.equal(await page.locator('.mv-lane[data-track=camera]').getAttribute('data-probe'), `2:${rowHeight}:0`, 'laneDecorate gets the layout');

  // Extra lane after its track, in the Camera, Edit and All tabs only.
  const rows = () => page.evaluate(() => [...document.querySelectorAll('#mv-timeline-grid > .mv-lane')].map((lane) => lane.dataset.track || lane.dataset.extra));
  assert.deepEqual(await rows(), ['camera', 'probe-rigs', 'mouth']);
  await page.locator('#mv-tab-mouth').click();
  assert.deepEqual(await rows(), ['mouth']);
  await page.locator('#mv-tab-edit').click();
  assert.deepEqual(await rows(), ['probe-rigs', 'camera', 'mouth'], 'Edit: plugin lanes, then the editable tracks');
  const hints = () => page.locator('#mv-timeline-grid .mv-lane-hint').count();
  assert.equal(await hints(), 0, 'the plugin counts edits: no hint');
  await page.evaluate(() => { window.probeNoEdits = true; window.probeCtx.renderTimeline(); });
  assert.equal(await hints(), 1, 'an empty plugin lane keeps the hint');
  assert.equal(Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent()), 0);
  await page.evaluate(() => { window.probeNoEdits = false; window.probeCtx.renderTimeline(); });
  assert.equal(await hints(), 0);
  await page.locator('#mv-tab-all').click();
  assert.equal(await page.locator('#probe-rig').count(), 1);
  assert.deepEqual(await page.evaluate(() => window.probeCtx.snapTargets()), [0, 0, 4, 4, 8], 'playhead and MainCamera cuts');
  await page.locator('#mv-zoom').selectOption('48');
  const rig = await page.locator('#probe-rig').boundingBox();
  await page.mouse.move(rig.x + 30, rig.y + rig.height / 2);
  await page.mouse.down();
  await page.mouse.move(rig.x + 78, rig.y + rig.height / 2, { steps: 5 });
  await page.mouse.up();
  assert.deepEqual(await page.evaluate(() => [window.probeRigCommits, window.probeRigRange]), [['move'], { start: 3, end: 5 }],
    'ctx.attachDrag: 48 px at 48 px/s is one second, one commit');
  await page.locator('#mv-zoom').selectOption('fit');

  // Selection, constraints, value controls, header/footer, history via info.set.
  await page.locator('.mv-clip[data-event=cam-1]').click();
  assert.equal((await page.evaluate(() => window.probeCalls)).at(-1), 'select:cam-1');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=duration]').count(), 0, 'clipConstraints locks the length');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=start]').count(), 1, 'moving stays allowed');
  assert.equal(await page.locator('#mv-event-fields .mv-field-note').first().textContent(), 'Probe lock');
  assert.match(await page.locator('.mv-clip[data-event=cam-1]').getAttribute('title'), /Probe lock/);
  assert.deepEqual(await page.evaluate(() => window.probeTime), { time: 0, playing: false });
  await page.locator('.mv-clip[data-event=lip-1]').click();
  assert.equal(await page.locator('#probe-header').textContent(), 'header lip-1');
  assert.equal(await page.locator('#probe-footer').textContent(), 'footer');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=paramName]').count(), 0, 'valueControl null hides a key');
  assert.deepEqual(await page.evaluate(() => window.probeInfo), { key: 'weight', path: 'weight', value: .5, writable: true, original: undefined });
  await page.locator('#probe-weight').fill('.75');
  await page.locator('#probe-weight').press('Tab');
  await page.waitForFunction(() => window.probeCalls.at(-1) === 'project:history:do');
  assert.equal((await page.evaluate(() => MVStudio.getState().project.tracks[1].events[0].values.weight)), .75);
  assert.equal(Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent()), 3);
  await page.locator('.mv-clip[data-event=lip-1]').click();
  assert.equal(await page.evaluate(() => window.probeInfo.original), .5, 'info.original is the value before the first edit');

  // Gestures (spec §6.1): one undo step per press, or per picker when the control's UI
  // runs after the release. The host never closes a gesture at a release; it closes
  // one a control left open once the user moves on (a press, a key or an edit elsewhere).
  const steps = () => page.evaluate(() => ({ undo: window.probeCtx.history.size().undo,
    label: window.probeCtx.history.peekUndo()?.label, open: window.probeCtx.history.gestureActive }));
  const lip = () => page.evaluate(() => MVStudio.getState().project.tracks[1].events[0]);
  const settle = () => page.evaluate(() => new Promise((resolve) => setTimeout(() => requestAnimationFrame(() => resolve()), 50)));
  // A real primary press (and drag by dx px) at a fraction x of the element's width.
  const press = async (selector, { x = .5, dx = 0 } = {}) => {
    await page.locator(selector).scrollIntoViewIfNeeded();
    const box = await page.locator(selector).boundingBox();
    const left = box.x + box.width * x, y = box.y + box.height / 2;
    await page.mouse.move(left, y);
    await page.mouse.down();
    if (dx) await page.mouse.move(left + dx, y, { steps: 6 });
    await page.mouse.up();
  };
  // The native colour picker: what it writes arrives as input events after the
  // swatch's release, then change when it closes with a new colour. Escape closes the
  // picker headless Chromium opens (keys go to it while it is up).
  const pick = async (colours, change = true) => {
    await page.evaluate(async ([list, done]) => {
      for (const colour of list) {
        await new Promise((resolve) => setTimeout(resolve, 30));
        const swatch = document.getElementById('probe-tint');
        swatch.value = colour;
        swatch.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (done) document.getElementById('probe-tint').dispatchEvent(new Event('change', { bubbles: true }));
    }, [colours, change]);
    await page.keyboard.press('Escape');
  };
  const before = (await steps()).undo;
  const original = await lip();
  await press('#probe-tint');
  await settle();
  assert.equal((await steps()).open, true, 'the swatch gesture outlives its release while the picker is up');
  await pick(['#336699', '#4477aa', '#5588bb']);
  assert.deepEqual(await steps(), { undo: before + 1, label: 'Edit value', open: false }, 'one colour pick is one undo step');
  assert.deepEqual((await lip()).values.tint, { r: 0x55 / 255, g: 0x88 / 255, b: 0xbb / 255, a: 1 });

  // A slider drag in a ctx.history gesture; history.end given straight to the change
  // listener gets the Event and still ends it.
  await press('#probe-intensity', { dx: 60 });
  await settle();
  assert.deepEqual(await steps(), { undo: before + 2, label: 'Edit value', open: false }, 'a slider drag is one step, ended by history.end as a listener');
  assert((await lip()).values.intensity > .5);

  // A clip drag afterwards is a step of its own.
  await press('.mv-clip[data-event=lip-1]', { x: .3, dx: 30 });
  assert.deepEqual(await steps(), { undo: before + 3, label: 'Move clip', open: false }, 'a clip drag is a step of its own');
  assert((await lip()).start > original.start);

  // A picker closed with no change event leaves its gesture open; the next press on
  // the swatch starts a new step.
  await press('#probe-tint');
  await pick(['#102030'], false);
  assert.deepEqual(await steps(), { undo: before + 4, label: 'Edit value', open: true });
  await press('#probe-tint');
  await pick(['#203040'], false);
  assert.deepEqual(await steps(), { undo: before + 5, label: 'Edit value', open: true }, 'each press on the swatch is a step of its own');
  // An edit through another control, typed without a press, closes it first.
  const label = page.locator('#mv-event-fields [data-mv-field=label]');
  await label.focus();
  await label.fill('B');
  await label.press('Tab');
  assert.deepEqual(await steps(), { undo: before + 6, label: 'Rename clip', open: false }, 'the rename is a step of its own');
  // So does a key once the picker is gone, even on the swatch: the probe's j writes
  // through ctx.history directly.
  await press('#probe-tint');
  await pick(['#304050'], false);
  assert.deepEqual(await steps(), { undo: before + 7, label: 'Edit value', open: true });
  assert.equal(await page.evaluate(() => document.activeElement.id), 'probe-tint');
  await page.keyboard.press('j');
  assert.deepEqual(await steps(), { undo: before + 8, label: 'Edit value', open: false }, 'the plugin key is a step of its own');
  assert.equal((await lip()).values.weight, .9);
  // A gesture begun from the keyboard belongs to the focused element: keys there keep it.
  await page.evaluate(() => { document.getElementById('probe-tint').focus(); window.probeCtx.history.begin('Edit value'); });
  await page.keyboard.press('h');
  assert.equal((await steps()).open, true, 'a key on the owner of a keyboard gesture keeps it');
  await page.evaluate(() => document.activeElement.blur());
  await page.keyboard.press('h');
  assert.equal((await steps()).open, false, 'a key elsewhere closes it');
  // begin() can name its owner (a popover): presses inside it keep the gesture.
  await page.evaluate(() => window.probeCtx.history.begin('Edit value', { owner: document.getElementById('mv-panel-probe') }));
  await press('#probe-panel-text');
  assert.equal((await steps()).open, true, 'a press inside the named owner keeps it');
  await press('#mv-timeline-label');
  assert.equal((await steps()).open, false, 'a press outside it closes it');
  assert.equal(await page.evaluate(() => {
    const token = window.probeCtx.history.begin('Other');
    window.probeTintGesture.end();   // late: its gesture was closed by the host
    const open = window.probeCtx.history.gestureActive;
    window.probeCtx.history.end(token);
    return open && !window.probeCtx.history.gestureActive;
  }), true, 'a late info.gesture.end() leaves a newer gesture open');
  for (let count = (await steps()).undo; count > before; count--) await page.keyboard.press('Control+z');
  assert.equal((await steps()).undo, before);
  assert.deepEqual(await lip(), original, 'undo brings the clip back');

  // Plugin shortcut after the built-in ones; plain keys in a text field are not shortcuts.
  await page.locator('#mv-timeline-label').click();
  await page.keyboard.press('k');
  assert.equal((await page.evaluate(() => window.probeCalls)).at(-1), 'key:k');
  await page.locator('#mv-track-search').focus();
  await page.keyboard.press('k');
  assert.equal((await page.evaluate(() => window.probeCalls)).filter((call) => call === 'key:k').length, 1);
  await page.locator('#mv-track-search').fill('');

  // Non-native project: duplicate and delete as undoable structure changes.
  await page.locator('.mv-clip[data-event=lip-1]').click();
  await page.locator('#mv-duplicate-clip').click();
  await page.locator('.mv-clip[data-event="mouth:u1"]').waitFor();
  let state = await page.evaluate(() => MVStudio.getState());
  assert.deepEqual(state.selection, { track: 'mouth', event: 'mouth:u1' });
  assert.deepEqual(state.project.tracks[1].events.map((event) => [event.id, event.start]), [['lip-1', 1], ['mouth:u1', 2]]);
  assert.equal(state.project.editor.originals['mouth:u1'], null);
  await page.locator('#mv-delete-clip').click();
  await page.waitForFunction(() => !document.querySelector('.mv-clip[data-event="mouth:u1"]'));
  assert.equal((await page.evaluate(() => MVStudio.getState().selection)), null);
  await page.locator('#mv-undo').click();
  await page.locator('.mv-clip[data-event="mouth:u1"]').waitFor();
  await page.locator('#mv-undo').click();
  await page.waitForFunction(() => !document.querySelector('.mv-clip[data-event="mouth:u1"]'));

  // Revert asks plugins first; the probe handles only cam-1.
  await page.locator('.mv-clip[data-event=cam-1]').click();
  await page.locator('#mv-event-fields [data-mv-field=fov]').fill('35');
  await page.locator('#mv-event-fields [data-mv-field=fov]').press('Tab');
  await page.locator('#mv-revert-clip').click();
  assert.equal((await page.evaluate(() => window.probeCalls)).at(-1), 'revert:cam-1');
  await page.locator('.mv-clip[data-event=lip-1]').click();
  await page.locator('#mv-revert-clip').click();
  assert.equal((await page.evaluate(() => MVStudio.getState().project.tracks[1].events[0].values.weight)), .5, 'built-in revert');

  // The editor layer (originals) is saved with the project and comes back on reopen.
  await page.locator('#mv-save').click();
  const link = page.locator('#mv-save-result a');
  await link.waitFor();
  const restored = await page.request.post(url + '/api/mv-studio/open', { data: { path: await link.getAttribute('title') } }).then((reply) => reply.json());
  const saved = (await page.evaluate(() => MVStudio.getState())).project;
  assert.deepEqual(restored.editor, saved.editor);
  assert.deepEqual(Object.keys(restored.editor.originals).sort(), ['cam-1', 'lip-1', 'mouth:u1']);
  assert.equal(restored.editor.originals['lip-1'].values.weight, .5);

  // beforeSave can refuse a save with a message.
  await page.evaluate(() => { window.probeRefuseSave = true; });
  await page.locator('#mv-save').click();
  await page.waitForFunction(() => document.getElementById('mv-status').textContent === 'Probe refuses to save');
  assert(await page.locator('#mv-status').evaluate((element) => element.classList.contains('mv-error')));
  assert.deepEqual(errors, []);
  await page.close();
}

/* Lane labels on a phone (390 x 844, touch). Group rows stay headings: bold, as high as their
   text lines (their 16 px marks do not raise a line), wrapping only after a "/" or a space. No
   label breaks a word that fits its width (the mute toggle and the badge sit in the text flow),
   and every toggle and badge keeps a 32 px touch target. */
async function phoneLanes(browser, url, project) {
  const page = await browser.newPage({ locale: 'ko', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  try {
    await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
      regions: [{ id: 'gl', label: 'Global (GL)' }], platforms: [{ id: 'android', label: 'Android' }],
      songs: [{ id: 12035, title: project.name, variants: [{ id: 1, label: 'MV' }] }] } }));
    await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
    await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: project }));
    await page.goto(url + '/#mv');
    await page.waitForFunction(() => MVStudio.getState().visible);
    await page.locator('#mv-import-game').click();
    await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
    await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
    await page.locator('#mv-game-load').click();
    await page.waitForFunction((name) => MVStudio.getState().project?.name === name, project.name);
    await page.locator('#mv-timeline-grid .mv-clip').first().waitFor();
    const rows = await page.evaluate(() => [...document.querySelectorAll('#mv-timeline-grid .mv-lane-label[data-track]')].map((label) => {
      const body = label.querySelector('.mv-lane-text'), style = getComputedStyle(label);
      const room = label.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const tops = new Set(), broken = [];
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.parentElement.getClientRects().length) continue;   // the path, hidden on phones
        for (const match of node.data.matchAll(/[^/\s]+\/?/g)) {
          const range = document.createRange();
          range.setStart(node, match.index);
          range.setEnd(node, match.index + match[0].length);
          const rects = [...range.getClientRects()].filter((rect) => rect.width > 0);
          for (const rect of rects) tops.add(Math.round(rect.top));
          const lines = new Set(rects.map((rect) => Math.round(rect.top)));
          if (lines.size > 1 && rects.reduce((sum, rect) => sum + rect.width, 0) <= room) broken.push(match[0]);
        }
      }
      const marks = [...label.querySelectorAll('.mv-lane-mute, .mv-lane-quality')].filter((mark) => mark.getClientRects().length).map((mark) => {
        const box = mark.getBoundingClientRect(), target = getComputedStyle(mark, '::before');
        return { quality: mark.classList.contains('mv-lane-quality'), height: box.height,
          target: Math.min(parseFloat(target.width) || box.width, parseFloat(target.height) || box.height) };
      });
      return { label: label.title, group: label.classList.contains('mv-lane-group'), height: label.getBoundingClientRect().height,
        lines: tops.size, lineHeight: parseFloat(getComputedStyle(body).lineHeight), minHeight: parseFloat(style.minHeight) || 0,
        weight: Number(getComputedStyle(body).fontWeight), broken, marks };
    }));
    const groups = rows.filter((row) => row.group);
    assert(groups.length >= 5, 'group rows');
    // A category's quality badge shows on its tracks' rows; the group heading leaves it out here.
    assert(rows.some((row) => !row.group && row.marks.some((mark) => mark.quality)), 'track rows keep their quality badges');
    assert(!groups.some((row) => row.marks.some((mark) => mark.quality)), 'no badge line on a group heading');
    assert(rows.filter((row) => !row.group).every((row) => row.marks.some((mark) => !mark.quality)), 'every track row has its mute toggle');
    for (const row of rows) {
      assert.deepEqual(row.broken, [], `${row.label}: no word that fits is broken`);
      for (const mark of row.marks) assert(mark.target >= 32, `${row.label}: a 32 px touch target (${mark.target})`);
    }
    for (const row of groups) {
      assert(row.weight >= 600, `${row.label}: a group row keeps its heading weight`);
      assert(row.height <= Math.max(row.minHeight, row.lines * row.lineHeight + 1) + 1.5,
        `${row.label}: ${row.height} px for ${row.lines} line(s) of ${row.lineHeight} px`);
      for (const mark of row.marks) assert(mark.height <= 16, `${row.label}: a small mark (${mark.height})`);
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), 0, 'no horizontal page scroll');
    await page.locator('#mv-timeline-grid .mv-lane-group').filter({ hasText: 'Coloring' }).first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(evidence, 'lanes-phone-ko.png') });
  } finally {
    await page.close();
  }
}

async function run() {
  const server = await startServer();
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ locale: 'ko', viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(server.url + '/#mv');
    await page.waitForFunction(() => MVStudio.getState().visible);
    assert(await page.locator('#mv-timeline-nav').isHidden(), 'no project, no tabs');

    // A local stage GLB gives the game projects a real model to load.
    await page.locator('#mv-open').click();
    await chooseFile(page, modded, 'stage-fixture.glb');
    await page.waitForFunction(() => !!MVStudio.getState().project?.stage?.glb);
    const local = (await state(page)).project;

    let response = null, release = null;
    const gameProject = ({ duet = false, name = 'Timeline 12035' } = {}) => {
      const data = timeline({ duet });
      const member = (position, label) => ({ id: `member-${position}`, label, position, glb: local.stage.glb,
        transform: { position: [position === 1 ? 0 : -1, 0, 0] }, costumeId: 11, viewStatus: 1, suitSource: 'memberInit',
        themeColor: position === 1 ? [.93, .38, .55, 1] : [.98, .8, .2, 1],
        costumes: [{ id: 11, name: '겨울 교복', asset: 'a' }, { id: 12, name: '무대 의상', asset: 'b' }] });
      return { ...local, name, duration: data.duration, nativeTimeline: true, tracks: data.tracks,
        source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12035, assetId: 1 },
        performers: duet ? [member(1, '우에하라 아유무'), member(2, 'Member 2')] : [member(1, '우에하라 아유무')],
        quality: { mode: 1, modes: [{ id: 1, label: 'Medium', values: { shadow: true } }],
          options: [{ key: 'shadow', label: 'Shadow', type: 'boolean' }], values: { shadow: true } } };
    };
    await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
      regions: [{ id: 'gl', label: 'Global (GL)' }], platforms: [{ id: 'android', label: 'Android' }],
      songs: [{ id: 12035, title: 'Timeline 12035', variants: [{ id: 1, label: 'MV' }] }] } }));
    await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
    await page.route('**/api/mv-studio/game?*', async (route) => {
      if (release) await release;
      return route.fulfill({ json: response });
    });
    const importGame = async (project) => {
      response = project;
      await page.locator('#mv-import-game').click();
      await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
      await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
      await page.locator('#mv-game-load').click();
      await page.waitForFunction((name) => MVStudio.getState().project?.name === name && !document.querySelector('#mv-import-game').disabled, project.name);
      await page.locator('#mv-timeline-grid .mv-clip').first().waitFor();
    };

    // ---- Tabs and counts on the 12035 structure --------------------------------------------
    const original = gameProject();
    await importGame(original);
    let opened = await state(page);
    assert.deepEqual(opened.project, JSON.parse(JSON.stringify(original)), 'an opened project is unchanged until the first edit');
    assert.equal(opened.project.editor, undefined);
    assert.equal(opened.tab, 'all', 'first visit: All');
    let tabs = await tabState(page);
    assert.deepEqual(tabs.map((tab) => `${tab.id}:${tab.text}:${tab.count}`), ['edit:편집:0', 'all:전체:1117', 'dance:댄스:2', 'camera:카메라:79',
      'expression:표정:96', 'mouth:입:272', 'lighting:조명:293', 'stage:무대:221', 'effects:이펙트:35', 'post:화면 효과:114', 'crowd:관객:5']);
    assert.deepEqual(tabs.filter((tab) => tab.tabIndex === 0).map((tab) => tab.id), ['all'], 'roving tabindex');
    assert.equal(await page.locator('#mv-tab-camera').getAttribute('title'), '트랙 2개 · 클립 79개');
    assert.equal(await page.locator('#mv-timeline-scroll').getAttribute('role'), 'tabpanel');
    assert.equal(await page.locator('#mv-timeline-scroll').getAttribute('aria-labelledby'), 'mv-tab-all');
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-group').count(), 25, 'GroupTracks are header rows in All');
    assert.equal((await laneTabs(page)).length, 42);
    assert.equal(await page.locator('#mv-track-summary').textContent(), '트랙 42개 · 클립 1117개 · 편집 0개');
    assert.deepEqual(await page.locator('#mv-member-filter [role=radio]').allTextContents(), ['전체 멤버', '1 · 우에하라 아유무']);
    await page.screenshot({ path: path.join(evidence, 'tabs-all-ko.png') });

    await page.locator('#mv-tab-camera').click();
    assert.deepEqual(await laneTabs(page), ['camera', 'camera'], 'the Camera tab shows only camera lanes');
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-group').count(), 0, 'groups only in All');
    assert(await page.locator('#mv-member-filter').isHidden(), 'no member-bound camera tracks: no chips');
    assert.equal(await page.locator('#mv-timeline-scroll').getAttribute('aria-labelledby'), 'mv-tab-camera');
    // Arrow keys move focus and activate; Home/End jump; ←/→ wrap.
    await page.locator('#mv-tab-camera').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal((await state(page)).tab, 'expression');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'mv-tab-expression');
    assert.deepEqual([...new Set(await laneTabs(page))], ['expression']);
    await page.keyboard.press('End');
    assert.equal((await state(page)).tab, 'crowd');
    await page.keyboard.press('ArrowRight');
    assert.equal((await state(page)).tab, 'edit', '→ wraps to the first tab');
    await page.keyboard.press('ArrowLeft');
    assert.equal((await state(page)).tab, 'crowd', '← wraps to the last tab');
    await page.keyboard.press('Home');
    assert.equal((await state(page)).tab, 'edit');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'mv-tab-edit');

    // ---- Edit tab: hint, then a value edit marks the clip and moves its track up ------------
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-hint').textContent(), '아직 편집한 항목이 없습니다. 편집할 수 있는 트랙은 아래에 있습니다.');
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-separator').textContent(), '편집 가능');
    assert(await page.locator('#mv-track-editable-only').isDisabled());
    const lipTrack = original.tracks.find((track) => track.label === 'Member1/LipSync');
    const lip = lipTrack.events[0];
    await page.locator(`.mv-clip[data-event="${lip.id}"]`).click();
    const weight = page.locator('[data-mv-field=weight]');
    assert.equal(await weight.inputValue(), '0.5');
    assert.equal((await state(page)).project.editor, undefined, 'selecting is not editing');
    await weight.fill('0.8');
    await weight.press('Tab');
    await page.waitForFunction((id) => document.querySelector(`.mv-clip[data-event="${id}"]`)?.dataset.edited === 'true', lip.id);
    let current = await state(page);
    assert.equal(findEvent(current.project, lip.id).values.weight, .8);
    assert.deepEqual(current.project.editor.originals[lip.id], lip, 'the original is kept before the first change');
    assert.equal(Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent()), 1);
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-hint').count(), 0);
    assert.equal((await laneLabels(page))[0], 'Member1/LipSync', 'the edited track comes first');
    assert(await page.locator('#mv-timeline-grid .mv-lane-label.mv-lane-edited').first().isVisible());
    assert.equal(await page.locator('#mv-event-fields .mv-edited-badge').textContent(), '편집됨');
    assert.equal(await page.locator('#mv-undo').getAttribute('title'), '실행 취소 (Ctrl+Z)\n값 편집 (weight)');
    await page.screenshot({ path: path.join(evidence, 'edit-tab-after-edit-ko.png') });

    // ---- Undo/redo: keyboard and buttons ---------------------------------------------------
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    await page.waitForFunction((id) => !document.querySelector(`.mv-clip[data-event="${id}"]`)?.dataset.edited, lip.id);
    current = await state(page);
    assert.equal(findEvent(current.project, lip.id).values.weight, .5);
    assert.deepEqual(current.history, { undo: 0, redo: 1, undoLabel: null, redoLabel: 'Edit value', version: current.history.version });
    assert.equal(Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent()), 0);
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-hint').count(), 1);
    assert(await page.locator('#mv-undo').isDisabled());
    assert.equal(await page.locator('#mv-redo').getAttribute('title'), '다시 실행 (Ctrl+Shift+Z)\n값 편집 (weight)');
    await page.screenshot({ path: path.join(evidence, 'undo-ko.png') });
    await page.keyboard.press('Control+Shift+z');
    await page.waitForFunction((id) => document.querySelector(`.mv-clip[data-event="${id}"]`)?.dataset.edited === 'true', lip.id);
    await page.locator('#mv-undo').click();
    assert.equal(findEvent((await state(page)).project, lip.id).values.weight, .5);
    await page.locator('#mv-redo').click();
    assert.equal(findEvent((await state(page)).project, lip.id).values.weight, .8);
    await page.keyboard.press('Control+y');
    assert.equal((await state(page)).history.redo, 0, 'Ctrl+Y with nothing to redo is harmless');
    await page.screenshot({ path: path.join(evidence, 'redo-ko.png') });

    // Clip name (exported as m_DisplayName).
    const label = page.locator('#mv-event-fields [data-mv-field=label]');
    await label.fill('입 모양 A');
    await label.press('Tab');
    await page.waitForFunction((id) => document.querySelector(`.mv-clip[data-event="${id}"]`)?.textContent === '입 모양 A', lip.id);
    assert.equal(findEvent((await state(page)).project, lip.id).label, '입 모양 A');
    assert.equal((await state(page)).history.undoLabel, 'Rename clip');

    // Duration: at least one frame, as a drag or a trim allows.
    const length = page.locator('#mv-event-fields [data-mv-field=duration]');
    assert.equal(Number(await length.getAttribute('min')), 1 / 60);
    await length.fill('0');
    await length.press('Tab');
    assert.equal(findEvent((await state(page)).project, lip.id).duration, 1 / 60, 'a zero duration is clamped to one frame');
    assert.equal(await length.inputValue(), String(1 / 60));
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert.equal(findEvent((await state(page)).project, lip.id).duration, lip.duration);

    // ---- Overlap blends follow a move: Member1/LipSync stores the editor's overlap blends -------
    await page.locator('#mv-tab-mouth').click();
    await page.locator('#mv-zoom').selectOption('48');
    const blendClip = lipTrack.events.find((event) => event.id === lipTrack.id + ':4');
    const blendTarget = page.locator(`.mv-clip[data-event="${blendClip.id}"]`);
    await blendTarget.scrollIntoViewIfNeeded();
    await blendTarget.click();
    assert.equal(await page.locator('#mv-event-fields [data-mv-field=blendIn]').count(), 0, 'derived blends are read-only');
    assert.equal(await page.locator('#mv-event-fields [data-mv-field=blendOut]').count(), 0);
    assert.equal(await page.locator('#mv-event-fields [data-mv-note=blend]').textContent(), '앞뒤 클립과 겹치는 길이로 정해집니다');
    const blendBase = await state(page);
    const editsBefore = Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent());
    await blendTarget.focus();
    await page.keyboard.press('Alt+ArrowRight');
    current = await state(page);
    const lipsNow = current.project.tracks.find((track) => track.id === lipTrack.id);
    assert.equal(current.history.undo, blendBase.history.undo + 1, 'the move and its blends are one step');
    assert(Interact.blendGate(lipsNow), 'the stored blends follow the new overlaps');
    const blendsBefore = Object.fromEntries(blendBase.project.tracks.find((track) => track.id === lipTrack.id).events
      .map((event) => [event.id, [event.values.blendIn, event.values.blendOut]]));
    const changedBlends = lipsNow.events.filter((event) => blendsBefore[event.id][0] !== event.values.blendIn ||
      blendsBefore[event.id][1] !== event.values.blendOut).map((event) => event.id);
    assert(changedBlends.includes(blendClip.id) && changedBlends.length >= 2, `the moved clip and a neighbour: ${changedBlends}`);
    assert.equal(Number(await page.locator('#mv-tab-edit .mv-tab-count').textContent()), editsBefore + 1,
      'only the moved clip counts as edited; derived blends do not');
    // The Tracks summary lists the neighbours whose blends follow (the register and apply plans count them).
    assert.match(await page.locator('#mv-track-summary').textContent(),
      new RegExp(` · 블렌드나 시간만 다시 계산된 클립 ${changedBlends.length - 1}개$`));
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert.deepEqual((await state(page)).project.tracks.find((track) => track.id === lipTrack.id),
      blendBase.project.tracks.find((track) => track.id === lipTrack.id), 'undo restores the clip and every blend');
    assert.doesNotMatch(await page.locator('#mv-track-summary').textContent(), /다시 계산된/);
    await page.locator('#mv-zoom').selectOption('fit');

    // ---- Track mute: the toggle on a leaf lane label (undoable, counted in the Edit tab) -------
    await page.locator('#mv-tab-all').click();
    const muteLips = page.locator(`.mv-lane-label:not(.mv-lane-group) .mv-lane-mute[data-track="${lipTrack.id}"]`);
    assert.equal(await muteLips.getAttribute('aria-pressed'), 'false');
    assert.equal(await muteLips.getAttribute('aria-label'), '트랙 음소거');
    const muteBase = await state(page), editsBeforeMute = await editCount(page);
    await muteLips.click();
    current = await state(page);
    assert.equal(findTrack(current.project, lipTrack.id).muted, true);
    assert.deepEqual(current.project.editor.tracks, { [lipTrack.id]: { muted: false } }, 'the original mute is kept for "edited"');
    assert.equal(current.history.undoLabel, 'Mute track');
    assert.equal(current.history.undo, muteBase.history.undo + 1);
    assert.equal(await muteLips.getAttribute('aria-pressed'), 'true');
    assert(await page.locator(`.mv-lane[data-track="${lipTrack.id}"]`).evaluate((lane) => lane.classList.contains('mv-lane-muted')));
    assert.equal(await editCount(page), editsBeforeMute + 1, 'a mute counts in the Edit tab');
    assert.equal(await page.locator('#mv-event-fields [data-mv-note=muted]').textContent(), '이 트랙은 음소거되어 미리보기에서 재생되지 않습니다.');
    await page.screenshot({ path: path.join(evidence, 'track-mute-ko.png') });
    // The Edit tab lists the muted track with the edited ones.
    await page.locator('#mv-tab-edit').click();
    assert((await laneLabels(page)).slice(0, 2).includes('Member1/LipSync'));
    await page.locator('#mv-tab-all').click();
    // Space on the focused toggle unmutes; the focus stays; the track is no longer edited.
    await muteLips.focus();
    await page.keyboard.press('Space');
    assert.equal(findTrack((await state(page)).project, lipTrack.id).muted, false);
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('mv-lane-mute')), true);
    assert.equal(await editCount(page), editsBeforeMute);
    await page.keyboard.press('Control+z');
    assert.equal(findTrack((await state(page)).project, lipTrack.id).muted, true);
    await page.keyboard.press('Control+z');
    current = await state(page);
    assert.deepEqual(findTrack(current.project, lipTrack.id), findTrack(muteBase.project, lipTrack.id), 'undo takes the mute back');
    assert.equal(current.project.editor.tracks, undefined, 'and its record');
    // The game sets the mute of a StageEffect category's tracks from its quality flag: the toggle explains why.
    const led = original.tracks.find((track) => track.label === 'StageEffect/Expert/Coloring/LED_panel_01');
    const ledMute = page.locator(`.mv-lane-label:not(.mv-lane-group) .mv-lane-mute[data-track="${led.id}"]`);
    assert.equal(await ledMute.getAttribute('aria-disabled'), 'true');
    assert.equal(await ledMute.getAttribute('aria-pressed'), null);
    await ledMute.click({ force: true });   // aria-disabled: Playwright would wait for it to be enabled
    assert.equal(await page.locator('#mv-status').textContent(), "이 트랙의 음소거는 MV가 시작될 때 게임이 '무대 색상 연출' 그래픽 설정에 따라 정합니다.");
    assert.equal(!!findTrack((await state(page)).project, led.id).muted, false);
    assert.equal((await state(page)).history.undo, muteBase.history.undo, 'no history step');
    // Quality badges on the StageEffect category lanes: the flag that mutes them in the game.
    const badges = await page.locator('#mv-timeline-grid .mv-lane-quality').evaluateAll((items) => items.map((item) =>
      [item.closest('.mv-lane-label').title, item.dataset.quality]));
    assert.deepEqual(badges.find(([label]) => label === 'StageEffect/Expert/Coloring'), ['StageEffect/Expert/Coloring', 'stage_coloring'], 'the category row');
    assert(badges.some(([, option]) => option === 'stage_flash_light'));
    assert(!badges.some(([label]) => label.endsWith('main_01_act')), 'not on an ActivationTrack');
    assert(!badges.some(([label]) => label.startsWith('Member1')));
    const ledBadge = page.locator(`.mv-lane-label:not(.mv-lane-group) .mv-lane-quality[data-track="${led.id}"]`);
    assert.equal(await ledBadge.getAttribute('aria-label'), "MV 그래픽 설정에서 '무대 색상 연출'이(가) 켜져 있을 때만 재생됩니다.");
    assert.deepEqual(await laneLabels(page).then((labels) => labels.filter((label) => label.endsWith('LED_panel_01'))),
      ['StageEffect/Expert/Coloring/LED_panel_01'], 'the badge adds no text to the lane name');
    await ledBadge.click();
    assert.equal(await page.locator('#mv-status').textContent(), "MV 그래픽 설정에서 '무대 색상 연출'이(가) 켜져 있을 때만 재생됩니다.");
    // A group's mute never reaches the game: a group row has no toggle (a muted one shows a mark, below).
    assert(await page.locator('.mv-lane-group').count() > 0);
    assert.equal(await page.locator('.mv-lane-group .mv-lane-mute').count(), 0);

    // ---- Drag a camera shot by one second ----------------------------------------------------
    await page.locator('#mv-tab-camera').click();
    await page.locator('#mv-zoom').selectOption('48');
    const shot = original.tracks.find((track) => track.label === 'CameraMotion/Camera1').events[1];
    const clip = page.locator(`.mv-clip[data-event="${shot.id}"]`);
    await clip.scrollIntoViewIfNeeded();
    const box = await clip.boundingBox();
    const undoBefore = (await state(page)).history.undo;
    const y = box.y + box.height / 2, x = box.x + 20;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + 24, y, { steps: 4 });
    await page.mouse.move(x + 48, y, { steps: 4 });
    await page.waitForFunction((id) => !!document.querySelector(`.mv-clip[data-event="${id}"]`)?.dataset.dragTime, shot.id);
    await page.screenshot({ path: path.join(evidence, 'clip-drag-ko.png') });
    await page.mouse.up();
    current = await state(page);
    const moved = findEvent(current.project, shot.id);
    assert(Math.abs(moved.start * 60 - Math.round(moved.start * 60)) < 1e-9, 'the start lands on the 1/60 s grid');
    assert(Math.abs(moved.start - (shot.start + 1)) <= 1 / 60 + 1e-9, `moved one second: ${shot.start} → ${moved.start}`);
    assert.equal(moved.duration, shot.duration);
    assert.equal(current.history.undo, undoBefore + 1, 'one drag, one undo step');
    assert.equal(current.history.undoLabel, 'Move clip');
    assert.equal(current.time, moved.start, 'the playhead follows the moved clip');
    // The camera track passes the extrapolation gate: the previous shot's hold now reaches the moved cut.
    const previous = findEvent(current.project, original.tracks.find((track) => track.label === 'CameraMotion/Camera1').events[0].id);
    assert(Math.abs(previous.values.postExtrapolationTime - (moved.start - previous.start - previous.duration)) < 1e-9);
    assert.equal(await page.locator('#mv-event-fields output').filter({ hasText: /^[0-9.]+$/ }).count() >= 2, true,
      'recomputed extrapolation times are read-only');
    assert.equal(await page.locator('#mv-event-fields [data-mv-field=postExtrapolationTime]').count(), 0);
    assert.equal(await page.locator('#mv-event-fields .mv-field-note').filter({ hasText: '게임이 다시 계산하는 값입니다' }).count(), 1);
    // A camera shot keeps its offset and speed. It offers the modes the preview plays: every mode
    // once the scene has cameraLocalTime (Loop, Ping-pong and Continue), else None and Hold.
    const shotModes = () => page.locator('#mv-event-fields [data-mv-field=postExtrapolationMode] option').evaluateAll(
      (options) => options.map((option) => option.value));
    const capsNote = () => page.locator('#mv-event-fields [data-mv-note=caps]').textContent();
    const reselectShot = async () => {
      await page.locator(`.mv-clip[data-event="${original.tracks.find((track) => track.label === 'CameraMotion/Camera1').events[0].id}"]`).click();
      await clip.click();
    };
    // Both previews: without cameraLocalTime (the scene before it plays Loop, Ping-pong and
    // Continue), and with it. The scene keeps its own copy, so only the host's choice changes.
    const playsEveryMode = await page.evaluate(() => {
      window.mvSceneLocalTime = MVStudioScene.cameraLocalTime;
      delete MVStudioScene.cameraLocalTime;
      return typeof window.mvSceneLocalTime === 'function';
    });
    await reselectShot();
    assert.deepEqual(await shotModes(), ['0', '1'], 'a hold-only preview: None and Hold');
    assert.equal(await capsNote(), '카메라 샷은 오프셋과 속도를 바꿀 수 없고, 미리보기에 나오는 없음과 정지만 고를 수 있습니다.');
    await page.evaluate(() => { MVStudioScene.cameraLocalTime = window.mvSceneLocalTime || (() => 0); });
    await reselectShot();
    assert.deepEqual(await shotModes(), ['0', '1', '2', '3', '4'], 'every mode the preview plays');
    assert.equal(await page.locator('#mv-event-fields [data-mv-field=clipIn]').count(), 0, 'the offset stays read only');
    assert.equal(await page.locator('#mv-event-fields [data-mv-field=timeScale]').count(), 0);
    assert.equal(await capsNote(), '카메라 샷은 오프셋과 속도를 바꿀 수 없습니다. 미리보기는 샷에서 읽은 샘플을 그대로 재생합니다.');
    // This tree's own preview.
    await page.evaluate((plays) => { if (!plays) delete MVStudioScene.cameraLocalTime; delete window.mvSceneLocalTime; }, playsEveryMode);
    await reselectShot();
    assert.deepEqual(await shotModes(), playsEveryMode ? ['0', '1', '2', '3', '4'] : ['0', '1']);
    // Alt+→ nudges one frame as one more step.
    await clip.focus();
    await page.keyboard.press('Alt+ArrowRight');
    assert(Math.abs(findEvent((await state(page)).project, shot.id).start - (moved.start + 1 / 60)) < 1e-9);
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert.equal(findEvent((await state(page)).project, shot.id).start, moved.start);

    // Revert on a gated track: the previous shot's stored original post time is stale
    // since the move, so the revert writes the recomputed one and the gate still holds.
    const cameraTrack = original.tracks.find((track) => track.label === 'CameraMotion/Camera1');
    const gated = () => page.evaluate((id) => MVStudioTimelineInteract.extrapolationGate(
      MVStudio.getState().project.tracks.find((track) => track.id === id)), cameraTrack.id);
    const undoBase = (await state(page)).history.undo;
    await page.locator(`.mv-clip[data-event="${previous.id}"]`).click();
    await label.fill('첫 컷');
    await label.press('Tab');
    await page.waitForFunction((id) => document.querySelector(`.mv-clip[data-event="${id}"]`)?.textContent === '첫 컷', previous.id);
    await page.locator('#mv-revert-clip').click();
    current = await state(page);
    assert.equal(current.history.undoLabel, 'Revert clip');
    const reverted = findEvent(current.project, previous.id);
    assert.equal(reverted.label, cameraTrack.events[0].label, 'the name is reverted');
    assert(Math.abs(reverted.values.postExtrapolationTime - (moved.start - reverted.start - reverted.duration)) < 1e-9,
      `the hold still reaches the moved cut: ${reverted.values.postExtrapolationTime}`);
    assert.notEqual(reverted.values.postExtrapolationTime, cameraTrack.events[0].values.postExtrapolationTime);
    assert.equal(await gated(), true, 'the camera track still passes the extrapolation gate after a revert');
    assert.equal(await page.locator(`.mv-clip[data-event="${previous.id}"]`).getAttribute('data-edited'), null, 'the reverted shot is not marked edited');
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    await page.keyboard.press('Control+z');
    assert.equal((await state(page)).history.undo, undoBase);
    assert.equal(await gated(), true);

    // Edit tab: the first nudge moves the track into the edited section (a full redraw);
    // the clip keeps the focus, so the second Alt+→ nudges again.
    await page.locator('#mv-tab-edit').click();
    const cheek = original.tracks.find((track) => track.label === 'Member1/Cheek').events[0];
    const cheekClip = page.locator(`.mv-clip[data-event="${cheek.id}"]`);
    const focusedEvent = () => page.evaluate(() => document.activeElement?.dataset?.event || document.activeElement?.tagName);
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-separator ~ .mv-lane[data-track] .mv-clip[data-event="' + cheek.id + '"]').count(), 1,
      'the unedited cheek track is listed below the separator');
    await cheekClip.focus();
    await page.keyboard.press('Alt+ArrowRight');
    assert.equal(await focusedEvent(), cheek.id, 'focus stays on the clip after the Edit tab redraw');
    assert.equal(await page.locator('#mv-timeline-grid .mv-lane-separator ~ .mv-lane[data-track] .mv-clip[data-event="' + cheek.id + '"]').count(), 0,
      'the nudged track moved to the edited section');
    await page.keyboard.press('Alt+ArrowRight');
    assert(Math.abs(findEvent((await state(page)).project, cheek.id).start - (cheek.start + 2 / 60)) < 1e-9, 'two nudges, two frames');
    assert.equal((await state(page)).history.undo, undoBase + 2, 'one step per key');
    await page.keyboard.press('Control+z');
    await page.keyboard.press('Control+z');
    assert.equal(findEvent((await state(page)).project, cheek.id).start, cheek.start);
    assert.equal(await focusedEvent(), cheek.id, 'an undo that moves the track back keeps the focus too');
    // A resize rebuild keeps the focus as well, without scrolling back to a clip out of view.
    const far = await page.evaluate(() => {
      document.activeElement.dataset.stale = 'true';
      const scroll = document.getElementById('mv-timeline-scroll');
      scroll.scrollLeft = scroll.scrollWidth;
      return scroll.scrollLeft;
    });
    assert(far > 1000, `scrolled away from the clip (${far})`);
    await page.setViewportSize({ width: 1200, height: 900 });
    await page.waitForFunction(() => innerWidth === 1200 && !document.activeElement?.dataset?.stale);
    assert.equal(await focusedEvent(), cheek.id, 'a resize rebuild keeps the focus');
    assert(Math.abs(await page.evaluate(() => document.getElementById('mv-timeline-scroll').scrollLeft) - far) < 2, 'and leaves the view where it was');
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForFunction(() => innerWidth === 1280);
    // A mute is carried over a costume re-import as well.
    await page.locator('#mv-tab-mouth').click();
    await page.locator(`.mv-lane-mute[data-track="${lipTrack.id}"]`).click();
    await page.locator('#mv-tab-camera').click();
    const edited = (await state(page)).project;

    // ---- Costume re-import keeps the edits; the tablist is inert while it runs -----------------
    await page.locator('#mv-performers summary').click();
    let releaseImport;
    release = new Promise((resolve) => { releaseImport = resolve; });
    response = gameProject();
    await page.locator('#mv-performer-costume').selectOption('1');
    await page.waitForFunction(() => document.getElementById('mv-timeline-nav').inert === true);
    assert(await page.locator('#mv-undo').isDisabled(), 'no undo during a game import');
    releaseImport();
    release = null;
    await page.waitForFunction(() => document.getElementById('mv-timeline-nav').inert === false && !document.querySelector('#mv-import-game').disabled);
    current = await state(page);
    assert.equal(findEvent(current.project, lip.id).values.weight, .8, 'value edit carried over');
    assert.equal(findEvent(current.project, lip.id).label, '입 모양 A');
    assert.equal(findEvent(current.project, shot.id).start, moved.start, 'timing edit carried over');
    assert.equal(findTrack(current.project, lipTrack.id).muted, true, 'mute carried over');
    assert.deepEqual(current.project.editor, edited.editor);
    assert.equal(current.history.undo, edited.history?.undo ?? current.history.undo);
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert.equal(!!findTrack((await state(page)).project, lipTrack.id).muted, false, 'the mute is the last step');
    await page.keyboard.press('Control+z');
    assert.equal(findEvent((await state(page)).project, shot.id).start, shot.start, 'history survives the re-import');
    await page.locator('#mv-performers summary').click();

    // ---- Tab memory per session; a stored tab missing from the next MV falls back to All --------
    await page.locator('#mv-tab-mouth').click();
    await page.reload();
    await page.waitForFunction(() => MVStudio.getState().visible);
    await importGame(gameProject());
    assert.equal((await state(page)).tab, 'mouth', 'tab restored from sessionStorage');
    assert.equal((await state(page)).history.undo, 0, 'a new import starts a new history');

    // ---- Member chips and search on a duet ---------------------------------------------------
    await importGame(gameProject({ duet: true, name: 'Timeline 12035 duet' }));
    assert.equal((await state(page)).tab, 'mouth');
    assert.deepEqual(await page.locator('#mv-member-filter [role=radio]').allTextContents(), ['전체 멤버', '1 · 우에하라 아유무', '멤버 2']);
    assert.deepEqual(await laneLabels(page), ['Member1/LipSync', 'Member2/LipSync']);
    await page.locator('#mv-member-filter [data-mv-member=""]').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#mv-member-filter [aria-checked=true]').textContent(), '1 · 우에하라 아유무');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.mvMember), '1');
    await page.keyboard.press('ArrowRight');
    assert.deepEqual(await laneLabels(page), ['Member2/LipSync'], 'member 2 only');
    assert.equal((await state(page)).filters.member, 2);
    await page.locator('#mv-tab-expression').click();
    assert.deepEqual(await laneLabels(page), ['Member2/Eye'], 'the member filter combines with every member tab');
    await page.screenshot({ path: path.join(evidence, 'member-chips-ko.png') });
    await page.locator('#mv-tab-camera').click();
    assert(await page.locator('#mv-member-filter').isHidden());
    assert.equal((await laneTabs(page)).length, 2, 'no member filter where no track is member-bound');
    await page.locator('#mv-tab-all').click();
    assert.deepEqual(await laneLabels(page), ['Member2/LipSync', 'Member2/Eye']);
    await page.locator('#mv-member-filter [data-mv-member=""]').click();
    const search = page.locator('#mv-track-search');
    assert.equal(await search.getAttribute('placeholder'), '트랙 이름 검색');
    await search.fill('led_PANEL');
    await page.waitForFunction(() => document.querySelectorAll('#mv-timeline-grid .mv-lane[data-track]').length === 4);
    assert.deepEqual((await laneLabels(page)).map((text) => text.split('/').pop()), ['LED_panel_01', 'LED_panel_02', 'LED_panel_03', 'LED_panel_04']);
    assert.deepEqual(await page.locator('#mv-timeline-grid .mv-lane-group').allTextContents(),
      ['StageEffect', 'StageEffect/Expert', 'StageEffect/Expert/Coloring'], 'only the groups holding a match');
    await page.screenshot({ path: path.join(evidence, 'search-ko.png') });
    // Member, search and tab survive a reload.
    await page.locator('#mv-member-filter [data-mv-member="2"]').click();
    await search.fill('');
    await search.fill('eye');
    await page.reload();
    await page.waitForFunction(() => MVStudio.getState().visible);
    await importGame(gameProject({ duet: true, name: 'Timeline 12035 duet' }));
    assert.equal(await page.locator('#mv-track-search').inputValue(), 'eye');
    assert.deepEqual((await state(page)).filters.member, 2);
    assert.deepEqual(await laneLabels(page), ['Member2/Eye']);
    // A remembered member the next MV does not have is ignored there, and kept for later.
    await page.locator('#mv-track-search').fill('');
    await importGame(gameProject());
    assert.equal((await state(page)).filters.member, null);
    assert.equal(await page.locator('#mv-member-filter [aria-checked=true]').textContent(), '전체 멤버');
    assert.equal((await state(page)).tab, 'all');
    assert.equal((await laneLabels(page)).length, 42, 'nothing filtered out');
    await importGame(gameProject({ duet: true, name: 'Timeline 12035 duet' }));
    assert.equal((await state(page)).filters.member, 2);
    // Editable only and native group combine with the tab.
    await page.locator('#mv-member-filter [data-mv-member=""]').click();
    await page.locator('#mv-tab-stage').click();
    await page.locator('#mv-tracks summary').scrollIntoViewIfNeeded();
    await page.locator('#mv-track-group').selectOption('StageEffect/Expert/Display');
    assert.deepEqual((await laneLabels(page)).map((text) => text.split('/').pop()), ['main_01_act', 'sub_01_act', 'main_01', 'sub_01']);
    await page.locator('#mv-track-editable-only').check();
    assert.deepEqual((await laneLabels(page)).map((text) => text.split('/').pop()), ['main_01', 'sub_01']);
    assert.equal(await page.locator('#mv-track-summary').textContent(), '트랙 2개 · 클립 18개 · 편집 0개');
    await page.locator('#mv-track-editable-only').uncheck();

    // Narrow and short-landscape layouts: the tabs scroll inside their row, the page does not.
    await page.locator('#mv-tab-all').click();
    for (const [width, height, name] of [[408, 760, 'layout-portrait-ko.png'], [700, 860, 'layout-narrow-ko.png'], [900, 420, 'layout-short-landscape-ko.png']]) {
      await page.setViewportSize({ width, height });
      await page.waitForFunction((expected) => innerWidth === expected, width);
      await page.waitForTimeout(150);
      const layout = await page.evaluate(() => {
        const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
        const tabs = document.getElementById('mv-timeline-tabs');
        return { pageOverflow: document.documentElement.scrollWidth - innerWidth, tabsScroll: tabs.scrollWidth > tabs.clientWidth,
          tabsTop: rect('#mv-timeline-tabs').top, controlsBottom: rect('.mv-timeline-toolbar .mv-controls').bottom,
          searchWidth: rect('#mv-track-search').width, toolbar: rect('.mv-timeline-toolbar').height, scroll: rect('#mv-timeline-scroll').height,
          tabsWidth: rect('#mv-timeline-tabs').width, navWidth: rect('#mv-timeline-nav').width, chipsWidth: rect('#mv-member-filter').width };
      });
      assert(layout.pageOverflow <= 0, `${name}: no horizontal page scroll (${layout.pageOverflow})`);
      assert(layout.tabsTop >= layout.controlsBottom - 1, `${name}: the tabs have their own row`);
      assert(layout.searchWidth >= 80, `${name}: the search stays usable`);
      assert(layout.scroll >= 60, `${name}: the lanes stay visible (${layout.scroll})`);
      if (width === 408) assert(layout.tabsScroll, 'the tablist scrolls horizontally on a phone');
      if (height === 420) {
        // One row for tabs, search and chips: the tabs keep 40 %, the chips at most 30 % (they scroll).
        assert(layout.tabsWidth >= .4 * layout.navWidth - 1, `${name}: the tabs keep room (${layout.tabsWidth} of ${layout.navWidth})`);
        assert(layout.chipsWidth > 0 && layout.chipsWidth <= .3 * layout.navWidth + 1, `${name}: the chips are capped (${layout.chipsWidth})`);
      }
      await page.screenshot({ path: path.join(evidence, name) });
    }
    await page.setViewportSize({ width: 1280, height: 900 });

    // ---- Timing fields the game does not use for a clip type are read only --------------------
    // A saved edit of one (made before it became read only) still loads and can be put back.
    const flashLabel = 'StageEffect/Expert/Flash Light/Live Flash Light Track';
    const legacy = gameProject({ name: 'Timeline 12035 legacy' });
    const flash = legacy.tracks.find((track) => track.label === flashLabel).events[0];
    legacy.editor = { version: 1, originals: { [flash.id]: JSON.parse(JSON.stringify(flash)) } };
    flash.values.postExtrapolationMode = 1;
    // A lip-sync clip moved 5 frames before blends were recomputed: every blend of the track is
    // as it was before the move, so the saved track does not follow the overlap rule.
    const savedLips = legacy.tracks.find((track) => track.label === 'Member1/LipSync');
    const movedLip = savedLips.events.find((event) => event.id === savedLips.id + ':4');
    legacy.editor.originals[movedLip.id] = JSON.parse(JSON.stringify(movedLip));
    movedLip.start = Math.round(movedLip.start * 60 + 5) / 60;
    assert.equal(Interact.blendGate(savedLips), false, 'the saved blends are stale');
    // Two camera shots overlap in this save (the second one is longer): the game crossfades them.
    const legacyCamera = legacy.tracks.find((track) => track.label === 'CameraMotion/Camera1');
    const longShot = legacyCamera.events[1];
    legacy.editor.originals[longShot.id] = JSON.parse(JSON.stringify(longShot));
    longShot.duration += .5;
    const cameraBlends = Interact.blendTimes(legacyCamera.events);
    for (const event of legacyCamera.events) Object.assign(event.values, cameraBlends.get(event.id));
    assert(longShot.values.blendOut > 0 && legacyCamera.events[2].values.blendIn > 0);
    // A muted group (as stock 11054 and 10120 have) shows its state and why it does not count.
    const mutedGroup = legacy.tracks.find((track) => track.label === 'StageEffect/Expert/Post');
    mutedGroup.muted = true;
    // This project's quality preset has the flash lights off.
    legacy.quality = { ...legacy.quality, options: [...legacy.quality.options, { key: 'stage_flash_light', label: '무대 점멸 조명', type: 'boolean' }],
      values: { ...legacy.quality.values, stage_flash_light: false } };
    await importGame(legacy);
    await page.locator('#mv-tab-lighting').click();
    await page.locator(`.mv-clip[data-event="${flash.id}"]`).click();
    assert.equal(await page.locator(`.mv-clip[data-event="${flash.id}"]`).getAttribute('data-edited'), 'true', 'the saved edit loads');
    for (const key of ['preExtrapolationMode', 'postExtrapolationMode', 'clipIn', 'timeScale']) {
      assert.equal(await page.locator(`#mv-event-fields [data-mv-field=${key}]`).count(), 0, key + ' is read only');
    }
    assert.equal(await page.locator('#mv-event-fields [data-mv-readonly=preExtrapolationMode]').textContent(), '없음');
    assert.equal(await page.locator('#mv-event-fields [data-mv-readonly=postExtrapolationMode]').textContent(), '정지');
    assert.equal(await page.locator('#mv-event-fields [data-mv-field=easeIn]').count(), 1, 'blending fields stay editable');
    assert.equal(await page.locator('#mv-event-fields [data-mv-note=caps]').textContent(), '이 클립 종류의 읽기 전용 시간 항목은 게임에서 쓰이지 않습니다.');
    assert.deepEqual(await page.locator('#mv-event-fields [data-mv-restore]').evaluateAll((buttons) => buttons.map((item) => item.dataset.mvRestore)),
      ['postExtrapolationMode'], 'only the edited read-only field can be put back');
    await page.screenshot({ path: path.join(evidence, 'timing-fields-ko.png') });
    await page.locator('#mv-event-fields [data-mv-restore=postExtrapolationMode]').click();
    await page.waitForFunction((id) => !document.querySelector(`.mv-clip[data-event="${id}"]`)?.dataset.edited, flash.id);
    assert.equal(findEvent((await state(page)).project, flash.id).values.postExtrapolationMode, 0);
    assert.equal((await state(page)).history.undoLabel, 'Edit value');
    assert.equal(await page.locator('#mv-event-fields [data-mv-restore]').count(), 0);
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert.equal(findEvent((await state(page)).project, flash.id).values.postExtrapolationMode, 1, 'undo brings the saved edit back');
    await page.locator('#mv-tab-all').click();
    const groupMark = page.locator(`.mv-lane-group .mv-lane-mute[data-track="${mutedGroup.id}"]`);
    assert.equal(await page.locator('.mv-lane-group .mv-lane-mute').count(), 1, 'only the muted group has a mark');
    assert.equal(await groupMark.getAttribute('aria-disabled'), 'true');
    assert.equal(await groupMark.getAttribute('aria-label'), '음소거된 그룹');
    await groupMark.click({ force: true });
    assert.equal(await page.locator('#mv-status').textContent(),
      '그룹 음소거는 게임에 반영되지 않습니다. 게임은 그룹 안의 각 트랙을 그 트랙의 음소거 설정대로 재생합니다.');
    assert.equal((await state(page)).project.tracks.find((track) => track.id === mutedGroup.id).muted, true, 'and stays muted');
    await page.locator('#mv-tab-lighting').click();
    // The quality badge shows the flag off, and follows the quality panel.
    const flashTrack = legacy.tracks.find((track) => track.label === flashLabel);
    const flashBadge = page.locator(`.mv-lane-quality[data-track="${flashTrack.id}"]`);
    assert(await flashBadge.evaluate((badge) => badge.classList.contains('mv-quality-off')));
    assert.equal(await flashBadge.getAttribute('aria-label'), "MV 그래픽 설정에서 '무대 점멸 조명'이(가) 꺼져 있어 게임은 이 트랙을 재생하지 않습니다.");
    assert.equal(await page.locator('#mv-event-fields [data-mv-note=quality]').textContent(),
      "MV 그래픽 설정에서 '무대 점멸 조명'이(가) 꺼져 있어 게임은 이 트랙을 재생하지 않습니다.");
    await page.screenshot({ path: path.join(evidence, 'quality-badge-off-ko.png') });
    await page.locator('#mv-quality summary').scrollIntoViewIfNeeded();
    if (!(await page.locator('#mv-quality').evaluate((panel) => panel.open))) await page.locator('#mv-quality summary').click();
    await page.locator('[data-mv-quality=stage_flash_light]').check();
    assert.equal(await flashBadge.evaluate((badge) => badge.classList.contains('mv-quality-off')), false);
    assert.equal(await page.locator('#mv-event-fields [data-mv-note=quality]').textContent(),
      "MV 그래픽 설정에서 '무대 점멸 조명'이(가) 켜져 있을 때만 재생됩니다.");
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert(await flashBadge.evaluate((badge) => badge.classList.contains('mv-quality-off')), 'undo turns it off again');
    // The stale lip-sync track keeps the gate its original clips pass: nothing is written on load,
    // its blends are read only, and the next move on the track rewrites every blend.
    const savedLipsNow = () => state(page).then((value) => findTrack(value.project, savedLips.id));
    assert.deepEqual((await savedLipsNow()).events, savedLips.events, 'nothing written on load');
    await page.locator('#mv-tab-mouth').click();
    await page.locator(`.mv-clip[data-event="${movedLip.id}"]`).click();
    assert.equal(await page.locator('#mv-event-fields [data-mv-field=blendIn]').count(), 0, 'gated: blends read only');
    assert.equal(await page.locator('#mv-event-fields [data-mv-note=blend]').count(), 1);
    const nextLip = page.locator(`.mv-clip[data-event="${savedLips.id}:7"]`);
    await nextLip.scrollIntoViewIfNeeded();
    await nextLip.focus();
    const lipUndo = (await state(page)).history.undo;
    await page.keyboard.press('Alt+ArrowRight');
    assert.equal((await state(page)).history.undo, lipUndo + 1);
    assert(Interact.blendGate(await savedLipsNow()), 'every blend follows the overlaps after the next move');
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert.deepEqual((await savedLipsNow()).events, savedLips.events, 'undo puts the saved blends back');
    // An overlapping camera shot says the preview cuts where the game crossfades; one that does not, nothing.
    await page.locator('#mv-tab-camera').click();
    for (const [event, expected] of [[longShot, 1], [legacyCamera.events[2], 1], [legacyCamera.events[3], 0]]) {
      await page.locator(`.mv-clip[data-event="${event.id}"]`).click();
      assert.equal(await page.locator('#mv-event-fields [data-mv-note=camera-blend]').count(), expected, event.id);
    }
    await page.locator(`.mv-clip[data-event="${longShot.id}"]`).click();
    assert.equal(await page.locator('#mv-event-fields [data-mv-note=camera-blend]').textContent(),
      '이 샷은 다른 샷과 겹칩니다. 게임은 두 샷을 겹쳐 전환하지만, 미리보기는 뒤의 샷으로 바로 바뀝니다.');

    // The English UI names the same tabs.
    await page.locator('#lang-select').selectOption('en');
    await page.waitForFunction(() => document.querySelector('#mv-tab-all')?.firstChild.textContent.trim() === 'All');
    assert.deepEqual((await tabState(page)).map((tab) => tab.text), ['Edit', 'All', 'Dance', 'Camera', 'Expression', 'Mouth', 'Lighting',
      'Stage', 'Effects', 'Screen effects', 'Crowd']);
    await page.locator('#lang-select').selectOption('ko');
    await page.waitForFunction(() => document.querySelector('#mv-tab-all')?.firstChild.textContent.trim() === '전체');

    assert.deepEqual(errors, []);
    await phoneLanes(browser, server.url, original);
    await pluginContract(browser, server.url);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.processHandle.kill();
    fs.rmSync(library, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
