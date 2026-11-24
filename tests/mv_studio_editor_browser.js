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

/* The plugin host contract lanes B, C and D build on (spec §2): a probe plugin
   registered before the page scripts records every hook it receives. The probe
   project is non-native, so clips can also be duplicated and deleted. */
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
        if (info.key !== 'weight') return undefined;
        window.probeInfo = { key: info.key, path: info.path, value: info.value, writable: info.writable, original: info.original };
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
            const clip = ctx.make('button', 'rig', { type: 'button', class: 'mv-rig-clip', id: 'probe-rig' });
            clip.style.left = `${2 * layout.pixelsPerSecond}px`;
            clip.style.width = `${2 * layout.pixelsPerSecond}px`;
            lane.append(clip);
          } }];
      },
      clipConstraints(ctx, track) { return track.id === 'camera' ? { resize: false, reason: 'Probe lock' } : undefined; },
      revertEvent(ctx, track, event) { if (event.id !== 'cam-1') return false; calls.push('revert:' + event.id); return true; },
      editedCount(ctx) { return ctx.project() ? 2 : 0; },
      keydown(ctx, event) { if (event.key !== 'k') return false; calls.push('key:k'); return true; },
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
  const project = { version: 1, name: 'Probe MV', duration: 20, nativeTimeline: false, assets: [], warnings: [],
    performers: [{ id: 'member-1', label: '우에하라 아유무', position: 1, transform: { position: [0, 0, 0] } }],
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 99, assetId: 1 },
    tracks: [
      { id: 'camera', kind: 'camera', binding: 'MainCamera', label: 'Camera', events: [
        { id: 'cam-1', label: 'Shot 1', start: 0, duration: 4, values: { fov: 30 }, editableValues: ['fov'] },
        { id: 'cam-2', label: 'Shot 2', start: 4, duration: 4, values: { fov: 40 }, editableValues: ['fov'] }] },
      { id: 'mouth', kind: 'mouth', binding: '/EntryPoint/Live/Members/Member1', label: 'Member1/LipSync', events: [
        { id: 'lip-1', label: 'A', start: 1, duration: 1, values: { weight: .5, paramName: 'a' }, editableValues: ['weight', 'paramName'] }] }] };
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
  assert.equal(await page.locator('.mv-lane[data-track=camera]').getAttribute('data-probe'), '2:30:0', 'laneDecorate gets the layout');

  // Extra lane after its track, in the Camera, Edit and All tabs only.
  const rows = () => page.evaluate(() => [...document.querySelectorAll('#mv-timeline-grid > .mv-lane')].map((lane) => lane.dataset.track || lane.dataset.extra));
  assert.deepEqual(await rows(), ['camera', 'probe-rigs', 'mouth']);
  await page.locator('#mv-tab-mouth').click();
  assert.deepEqual(await rows(), ['mouth']);
  await page.locator('#mv-tab-edit').click();
  assert.deepEqual(await rows(), ['probe-rigs', 'camera', 'mouth'], 'Edit: plugin lanes, then the editable tracks');
  await page.locator('#mv-tab-all').click();
  assert.equal(await page.locator('#probe-rig').count(), 1);

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

  // beforeSave can refuse a save with a message.
  await page.evaluate(() => { window.probeRefuseSave = true; });
  await page.locator('#mv-save').click();
  await page.waitForFunction(() => document.getElementById('mv-status').textContent === 'Probe refuses to save');
  assert(await page.locator('#mv-status').evaluate((element) => element.classList.contains('mv-error')));
  assert.deepEqual(errors, []);
  await page.close();
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
    assert.equal(await page.locator('#mv-undo').getAttribute('title'), '실행 취소: 값 편집 (weight)');
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
    assert.equal(await page.locator('#mv-redo').getAttribute('title'), '다시 실행: 값 편집 (weight)');
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
    // Alt+→ nudges one frame as one more step.
    await clip.focus();
    await page.keyboard.press('Alt+ArrowRight');
    assert(Math.abs(findEvent((await state(page)).project, shot.id).start - (moved.start + 1 / 60)) < 1e-9);
    await page.locator('#mv-timeline-label').click();
    await page.keyboard.press('Control+z');
    assert.equal(findEvent((await state(page)).project, shot.id).start, moved.start);
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
    assert.deepEqual(current.project.editor, edited.editor);
    assert.equal(current.history.undo, edited.history?.undo ?? current.history.undo);
    await page.locator('#mv-timeline-label').click();
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
          searchWidth: rect('#mv-track-search').width, toolbar: rect('.mv-timeline-toolbar').height, scroll: rect('#mv-timeline-scroll').height };
      });
      assert(layout.pageOverflow <= 0, `${name}: no horizontal page scroll (${layout.pageOverflow})`);
      assert(layout.tabsTop >= layout.controlsBottom - 1, `${name}: the tabs have their own row`);
      assert(layout.searchWidth >= 80, `${name}: the search stays usable`);
      assert(layout.scroll >= 60, `${name}: the lanes stay visible (${layout.scroll})`);
      if (width === 408) assert(layout.tabsScroll, 'the tablist scrolls horizontally on a phone');
      await page.screenshot({ path: path.join(evidence, name) });
    }
    await page.setViewportSize({ width: 1280, height: 900 });

    // The English UI names the same tabs.
    await page.locator('#lang-select').selectOption('en');
    await page.waitForFunction(() => document.querySelector('#mv-tab-all')?.firstChild.textContent.trim() === 'All');
    assert.deepEqual((await tabState(page)).map((tab) => tab.text), ['Edit', 'All', 'Dance', 'Camera', 'Expression', 'Mouth', 'Lighting',
      'Stage', 'Effects', 'Screen effects', 'Crowd']);
    await page.locator('#lang-select').selectOption('ko');
    await page.waitForFunction(() => document.querySelector('#mv-tab-all')?.firstChild.textContent.trim() === '전체');

    assert.deepEqual(errors, []);
    await pluginContract(browser, server.url);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.processHandle.kill();
    fs.rmSync(library, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
