/* Shared MV workbench, a real local GLB/ZIP round-trip and a synthetic game catalog. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');

const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-studio-library-'));
const modded = path.join(library, 'modded');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-studio-browser-'));
const modelName = 'stage-fixture.glb';
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(modded, modelName), fixture().glb);
const wav = Buffer.alloc(44 + 160000);
wav.write('RIFF', 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32);
wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
fs.writeFileSync(path.join(modded, 'soundtrack.wav'), wav);

async function startServer() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const processLog = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const processHandle = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)], {
    cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', processLog, processLog],
  });
  fs.closeSync(processLog);
  const url = 'http://127.0.0.1:' + port;
  for (let count = 0; count < 100; count++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { processHandle, url }; } catch (_) {}
    if (processHandle.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  processHandle.kill();
  throw new Error('Isolated workbench did not start');
}

async function chooseLocal(page, folder, file) {
  await page.locator('#mv-open').click();
  await chooseFile(page, folder, file);
}

async function chooseFile(page, folder, file) {
  await page.waitForFunction(expected => document.getElementById('picker-crumb').textContent === expected, folder);
  await page.locator('#picker-entries li').filter({ hasText: file }).click();
}

// MV-only song registration panel (mv-studio-register.js) on mocked routes: defaults, project audio
// decoded and uploaded as 44.1 kHz stereo PCM with the offset trimmed, the missing-iOS consent,
// the register-job payload, the success text, "fix" for a legacy song and the base MV picker.
async function registrationControls(page) {
  const project = await page.evaluate(() => MVStudio.getState().project);
  const soundtrack = { origin: 'project', offset: project.soundtrack.offset, duration: project.soundtrack.duration,
    url: project.soundtrack.url };
  let unbased = false;
  const plan = () => unbased ? {
    region: 'gl', base: null, song: null, targets: [], target: 'new', title: 'MV Studio sample', credit: '', platforms: {},
    projectPlatform: null, timeline: { native: false, unchanged: true, bake: [], download: [], missing: [], keep: [] },
    edits: {}, notInGame: [], blocked: [{ message: 'Choose the base MV.' }], warnings: [],
    audio: { default: 'base', encoder: true, soundtrack, beat: null, previewStart: 0 }, jacket: { default: 'base' }, encoder: true,
  } : {
    region: 'gl', base: { liveId: 12, assetId: 34, title: 'MV Studio sample', stage: '별빛 무대', fixed: true, registered: false },
    song: null, targets: [], target: 'new', title: 'MV Studio sample', credit: '',
    platforms: { android: { status: 'project' }, ios: { status: 'download', bytes: 314572 } }, projectPlatform: 'android',
    timeline: { native: true, unchanged: false, bake: ['android', 'ios'], download: ['ios'], missing: [], keep: [] },
    edits: { cameraShots: 1, values: 2, timing: 1, clips: 3, follow: false }, notInGame: [{ message: 'Member positions' }],
    blocked: [], warnings: [], audio: { default: 'project', encoder: true, soundtrack, beat: null, previewStart: 0 },
    jacket: { default: 'base' }, encoder: true, managedRestart: false,
  };
  const plans = [], jobs = [];
  let pcm = null;
  await page.route('**/api/mv-studio/registration-plan?*', (route) => { plans.push(route.request().postDataJSON()); return route.fulfill({ json: plan() }); });
  await page.route('**/api/mv-studio/songs?*', (route) => route.fulfill({ json: { region: 'gl', encoder: true, managedRestart: false,
    songs: [{ liveId: 93000, region: 'gl', title: '옛 등록 곡', visible: false, actions: ['fix', 'remove'], templateAssetId: 34,
      platforms: { android: 'stock', ios: 'stock' }, updatedAt: 1764000000 }] } }));
  await page.route('**/api/mv-studio/pcm?*', (route) => { pcm = route.request().postDataBuffer();
    return route.fulfill({ json: { name: 'a'.repeat(32) + '.wav', duration: 9.25 } }); });
  await page.route('**/api/mv-studio/register-job?*', (route) => { jobs.push(route.request().postDataJSON());
    return route.fulfill({ json: { job_id: 'job' + jobs.length } }); });
  const stream = (events) => events.map((event) => 'data: ' + JSON.stringify(event) + '\n\n').join('');
  await page.route('**/api/jobs/job1/events', (route) => route.fulfill({ headers: { 'Content-Type': 'text/event-stream' }, body: stream([
    { type: 'mv-stage', stage: 'check', label: 'Checking the base MV originals', index: 0, total: 3 },
    { type: 'mv-stage', stage: 'android', label: 'Building the Android timeline', index: 1, total: 3 },
    { type: 'mv-song', mode: 'new', changed: true, restart: 'manual', warnings: [],
      song: { liveId: 93001, region: 'gl', title: 'MV Studio sample' } },
    { type: 'done', status: 'done', summary: 'ok' }]) }));
  await page.route('**/api/jobs/job2/events', (route) => route.fulfill({ headers: { 'Content-Type': 'text/event-stream' }, body: stream([
    { type: 'mv-song', mode: 'update', changed: true, restart: 'manual', warnings: [], song: { liveId: 93000, region: 'gl', title: '옛 등록 곡' } },
    { type: 'done', status: 'done', summary: 'ok' }]) }));
  const panel = page.locator('#mv-panel-register');
  assert.equal(await panel.locator(':scope > summary').textContent(), 'MV 전용 곡으로 등록');
  await panel.locator(':scope > summary').click();
  await page.locator('#mv-register-base').filter({ hasText: '별빛 무대' }).waitFor();
  assert.equal(plans[0].project.source.liveId, 12);
  assert.deepEqual(plans[0].unbaked, []);
  assert.equal(await page.locator('#mv-register-title').inputValue(), 'MV Studio sample');
  assert(await page.locator('input[name=mv-register-audio][value=project]').isChecked());
  assert(await page.locator('#mv-register-submit').isDisabled(), 'Project audio needs its BPM first');
  assert.match(await page.locator('#mv-register-plan').textContent(), /카메라 1컷 수정/);
  assert.match(await page.locator('#mv-register-plan').textContent(), /게임에 들어가지 않음: 멤버 위치/);
  assert(!(await page.locator('#mv-register-download').isChecked()));
  await page.locator('#mv-register-bpm').fill('120');
  await page.locator('#mv-register-first-beat').fill('0.5');
  await page.locator('#mv-register-submit').click();
  const consent = page.locator('#mv-register-confirm');
  await consent.waitFor();
  assert.equal(await consent.locator('p').textContent(), 'iOS에서는 원래 MV가 재생됩니다. 계속할까요?');
  await page.locator('#mv-register-confirm-yes').click();
  await page.locator('#mv-register-result').filter({ hasText: '등록했습니다' }).waitFor();
  assert.match(await page.locator('#mv-register-result').textContent(), /'MV Studio sample'\(93001\)를 등록했습니다\..*게임 서버를 다시 시작해야 적용됩니다\./);
  // 16-bit 44.1 kHz stereo PCM; the 10 s soundtrack starts 0.75 s in (audio time = director time + offset).
  assert.equal(pcm.toString('ascii', 0, 4), 'RIFF');
  assert.equal(pcm.toString('ascii', 8, 16), 'WAVEfmt ');
  assert.deepEqual([pcm.readUInt16LE(20), pcm.readUInt16LE(22), pcm.readUInt32LE(24), pcm.readUInt16LE(34)], [1, 2, 44100, 16]);
  assert.equal(pcm.readUInt32LE(40), pcm.length - 44);
  assert(Math.abs((pcm.length - 44) / 4 - (10 - 0.75) * 44100) <= 1, String(pcm.length));
  const { project: posted, ...request } = jobs[0];
  assert.equal(posted.source.liveId, 12);
  assert.deepEqual(request, { mode: 'new', title: 'MV Studio sample', credit: null, jacket: { kind: 'base' },
    audio: { kind: 'project', pcm: 'a'.repeat(32) + '.wav', bpm: 120, firstBeat: 0.5, previewStart: 0 },
    platforms: ['android'], download: false, unbaked: [] });
  assert.deepEqual(await page.evaluate(() => MVStudio.getState().project.registration), { region: 'gl', liveId: 93001 });
  // A legacy song without its Advanced chart: "Fix" runs an update that only adds the placeholder.
  unbased = true;
  await page.locator('#mv-register-songs > summary').click();
  const legacy = page.locator('[data-mv-song="93000"]');
  await legacy.waitFor();
  assert.match(await legacy.textContent(), /게임에 보이지 않음 \(상급 채보 없음\)/);
  await legacy.locator('[data-mv-song-action=fix]').click();
  await page.waitForFunction(() => document.querySelector('#mv-register-base-change'));
  assert.deepEqual(jobs[1], { mode: 'update', region: 'gl', liveId: 93000, addPlaceholder: true });
  // A project without a game base: Register stays disabled until a base MV is chosen from the catalog.
  assert(await page.locator('#mv-register-submit').isDisabled());
  assert.match(await page.locator('#mv-register-plan').textContent(), /기본 MV를 고르세요\./);
  await page.locator('#mv-register-base-change').click();
  await page.locator('#mv-register-base-song option').first().waitFor({ state: 'attached' });
  assert.deepEqual(await page.locator('#mv-register-base-song option').allTextContents(), ['다른 노래 (13)']);
  const before = plans.length;
  unbased = false;
  await page.locator('#mv-register-base-use').click();
  await page.waitForFunction(() => !document.querySelector('#mv-register-picker'));
  for (let tries = 0; tries < 100 && plans.length === before; tries++) await page.waitForTimeout(50);
  assert.deepEqual(plans[plans.length - 1].template, { region: 'gl', liveId: 13, assetId: 35 });
  await page.unroute('**/api/mv-studio/registration-plan?*');
  await page.unroute('**/api/mv-studio/songs?*');
  await page.unroute('**/api/mv-studio/pcm?*');
  await page.unroute('**/api/mv-studio/register-job?*');
  await panel.locator(':scope > summary').click();
}

async function localAndGame(page, url) {
  await page.goto(url + '/#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  let releaseModel;
  const waitingForModel = new Promise(resolve => { releaseModel = resolve; });
  const delayedModel = async route => { await waitingForModel; await route.continue(); };
  await page.route('**/api/mv-studio/media/*.glb', delayedModel);
  try {
    await chooseLocal(page, modded, modelName);
    await page.waitForFunction(() => !!MVStudio.getState().project?.stage?.glb);
    assert.equal(await page.locator('#mv-project-title').textContent(), 'stage-fixture');
    assert(await page.locator('#mv-timeline-scroll').isVisible());
    assert(await page.locator('#mv-save').isDisabled());
    assert(!(await page.locator('#mv-camera-mode').isVisible()));
  } finally { releaseModel(); }
  await page.locator('#mv-camera-mode').waitFor();
  await page.unroute('**/api/mv-studio/media/*.glb', delayedModel);
  const local = await page.evaluate(() => MVStudio.getState().project);
  assert(local.assets.find(asset => asset.kind === 'stage'));
  assert(await page.locator('#mv-scene canvas').isVisible());
  assert(await page.locator('#mv-camera-mode').isVisible());
  await page.locator('#mv-camera-mode').selectOption('orbit');
  await page.locator('#mv-frame-scene').click();
  const soundtrack = await page.request.post(url + '/api/mv-studio/asset', {
    data: { path: path.join(modded, 'soundtrack.wav'), kind: 'audio' },
  }).then(response => response.json());
  assert(soundtrack.soundtrack.url);

  const gameProject = { ...local, name: 'MV Studio sample', duration: 35,
    performers: [{ id: 'actor-1', label: 'Actor 1', position: 1, glb: local.stage.glb, transform: { position: [0, 0, 0] },
      costumeId: 51, viewStatus: 1, suitSource: 'memberInit',
      costumes: [{ id: 51, name: 'Winter uniform', asset: 'a' }, { id: 52, name: 'Stage suit', asset: 'b' },
        { id: 52, name: 'Stage suit', asset: 'c', viewStatus: 2 }] }],
    soundtrack: soundtrack.soundtrack,
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12, assetId: 34, mvOnly: true },
    tracks: [{ id: 'camera', label: 'Camera', kind: 'camera', binding: 'MainCamera', events: [{ id: 'sample-clip',
      label: 'Opening camera', start: 2, duration: 8, values: { fov: 40, fixed: 1 }, editableValues: ['fov'] }] },
    { id: 'light', label: 'Light', kind: 'lighting', events: [{ id: 'light-clip', label: 'Opening light',
      start: 0, duration: 4, values: {} }] }],
    quality: { mode: 1, modes: [{ id: 1, label: 'Medium', values: { shadow: true } }],
      options: [{ key: 'shadow', label: 'Shadow', type: 'boolean' }], values: { shadow: true } },
  };
  let catalogRequests = 0, catalogPlayers = [];
  await page.route('**/api/mv-studio/catalog?*', route => {
    catalogRequests++;
    return route.fulfill({ json: { region: 'gl', platform: 'android',
      regions: [{ id: 'gl', label: 'Global (GL)' }], platforms: [{ id: 'android', label: 'Android' }],
      songs: [{ id: 12, title: 'MV Studio sample', mvOnly: true, variants: [{ id: 34, label: 'MV' }] },
        { id: 13, title: '다른 노래', variants: [{ id: 35, label: '별빛 무대' }] }],
      players: catalogPlayers,
    } });
  });
  let request;
  await page.route('**/api/mv-studio/game-stream?*', route => route.fulfill({ status: 404 }));
  await page.route('**/api/mv-studio/game?*', route => {
    request = route.request().postDataJSON();
    return route.fulfill({ json: gameProject });
  });
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  const search = page.locator('#mv-game-search');
  await search.fill('별빛');
  assert.equal(await page.locator('#mv-game-song').inputValue(), '13');
  await search.fill('ｍｖ studio');
  assert.equal(await page.locator('#mv-game-song').inputValue(), '12');
  assert.match(await page.locator('#mv-game-song option').textContent(), /MV 전용/);
  await page.locator('#mv-game-load').click();
  await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
  assert.equal(catalogRequests, 1);
  assert.deepEqual(request, { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false });
  await page.locator('#mv-performers summary').click();
  // The costume override re-imports the game MV with the suit and m_suit_view model pinned.
  const costume = page.locator('#mv-performer-costume');
  assert.equal(await costume.inputValue(), '0');
  assert.deepEqual(await costume.locator('option').allTextContents(),
    ['Winter uniform (51)', 'Stage suit (52)', 'Stage suit (52 · 뷰 상태 2)']);
  request = null;
  await costume.selectOption('2');
  await page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled);
  await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
  assert.deepEqual(request, { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false,
    costumes: { 1: { suit: 52, viewStatus: 2 } } });
  // The deck tab and player choice travel with the next picker import.
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  assert(await page.locator('#mv-game-player-field').isHidden(), 'No player database, no player choice');
  await page.locator('#mv-game-deck').selectOption('1');
  request = null;
  await page.locator('#mv-game-load').click();
  await page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled);
  await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
  assert.deepEqual(request, { region: 'gl', platform: 'android', liveId: 12, assetId: 34, download: false, deck: { deckType: 1 } });
  // A lone local player is preselected until a choice is made; a catalog reload keeps "New player".
  catalogPlayers = [{ id: 7, name: 'Player' }];
  const pickerImport = async (choose) => {
    await page.locator('#mv-import-game').click();
    await page.locator('#mv-game-player-field').waitFor();
    await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
    if (choose !== undefined) await page.locator('#mv-game-player').selectOption(choose);
    const chosen = await page.locator('#mv-game-player').inputValue();
    request = null;
    await page.locator('#mv-game-load').click();
    await page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled);
    await page.locator('.mv-clip[data-event=sample-clip]').waitFor();
    return chosen;
  };
  assert.equal(await pickerImport(), '7');
  assert.deepEqual(request.deck, { deckType: 1, userId: 7 });
  assert.deepEqual(await page.locator('#mv-game-player option').allTextContents(), ['새 플레이어', 'Player (7)']);
  assert.equal(await pickerImport(''), '');
  assert.deepEqual(request.deck, { deckType: 1 });
  assert.equal(await pickerImport(), '', 'A reload must not re-preselect after "New player" was chosen');
  assert.deepEqual(request.deck, { deckType: 1 });
  if (!(await page.locator('#mv-performer-costume').isVisible())) await page.locator('#mv-performers summary').click();
  const position = page.locator('[data-mv-performer-axis=X]');
  await position.fill('1.25'); await position.press('Tab');
  await page.locator('#mv-performers summary').click();
  await page.locator('#mv-soundtrack summary').click();
  const soundtrackOffset = page.locator('#mv-soundtrack-offset');
  await soundtrackOffset.fill('0.75'); await soundtrackOffset.press('Tab');
  await page.locator('#mv-soundtrack summary').click();
  const scrubbedTimes = await page.evaluate(async () => {
    const range = document.getElementById('mv-seek');
    const scrub = value => {
      range.value = value;
      range.dispatchEvent(new Event('input', { bubbles: true }));
      return MVStudio.getState().time;
    };
    const inputs = [scrub(1.25), scrub(4.75)];
    range.dispatchEvent(new Event('change', { bubbles: true }));
    const committed = MVStudio.getState().time;
    scrub(30);
    document.querySelector('.mv-clip[data-event=sample-clip]').click();
    await new Promise(resolve => requestAnimationFrame(resolve));
    return { inputs, committed, selected: MVStudio.getState().time };
  });
  assert.deepEqual(scrubbedTimes, { inputs: [1.25, 4.75], committed: 4.75, selected: 2 });
  assert.equal(await page.locator('[data-mv-field=fixed]').count(), 0);
  const untouched = await page.locator('.mv-clip[data-event=light-clip]').elementHandle();
  const clip = page.locator('.mv-clip[data-event=sample-clip]');
  const originalWidth = await clip.evaluate(element => element.style.width);
  const start = page.locator('[data-mv-field=start]');
  await start.fill('7.5');
  await start.press('Tab');
  assert.equal(await page.evaluate(() => MVStudio.getState().time), 7.5);
  const duration = page.locator('[data-mv-field=duration]');
  await duration.fill('11.5');
  await duration.press('Tab');
  assert(await untouched.evaluate(element => element.isConnected));
  assert.notEqual(await clip.evaluate(element => element.style.width), originalWidth);
  assert.equal(await clip.getAttribute('aria-pressed'), 'true');
  const fov = page.locator('[data-mv-field=fov]');
  await fov.fill('60');
  await fov.press('Tab');
  await page.locator('#mv-quality summary').click();
  const shadow = page.locator('[data-mv-quality=shadow]');
  await shadow.uncheck();
  // The device option is offered off by default and is not saved with the project.
  const refresh = page.locator('#mv-refresh-rate-mode');
  assert.equal(await refresh.inputValue(), '0');
  assert.deepEqual(await refresh.locator('option').evaluateAll(options => options.map(option => option.value)), ['0', '60', '90', '120']);
  await refresh.selectOption('120');
  assert.equal(await page.locator('#mv-refresh-rate-mode').inputValue(), '120');
  await page.locator('#mv-refresh-rate-mode').selectOption('0');
  // So is the player's anti-aliasing option.
  const antiAliasing = page.locator('#mv-anti-aliasing');
  assert.equal(await antiAliasing.isChecked(), false);
  await antiAliasing.check();
  assert.equal(await page.locator('#mv-anti-aliasing').isChecked(), true);
  await page.locator('#mv-anti-aliasing').uncheck();
  await page.locator('#mv-panel-menu summary').click();
  await page.locator('[data-mv-panel-option=quality]').uncheck();
  assert(!(await shadow.isVisible()));
  await page.locator('[data-mv-panel-option=quality]').check();
  assert(await shadow.isVisible());
  await page.locator('#mv-panel-menu summary').click();
  await page.locator('#mv-play').click();
  await page.waitForFunction(() => MVStudio.getState().time > 7.55);
  await page.locator('[data-tab=tools]').click();
  assert.equal(await page.evaluate(() => MVStudio.getState().playing), false);
  await page.locator('[data-tab=mv]').click();

  await page.locator('#mv-save').click();
  const link = page.locator('#mv-save-result a');
  await link.waitFor();
  const saved = await link.getAttribute('title');
  assert.match(saved, /\.mv-project\.zip$/);
  assert(await page.request.get(await link.getAttribute('href')).then(response => response.ok()));
  const restored = await page.request.post(url + '/api/mv-studio/open', { data: { path: saved } }).then(response => response.json());
  assert.equal(restored.tracks[0].events[0].start, 7.5);
  assert.equal(restored.tracks[0].events[0].duration, 11.5);
  assert.equal(restored.tracks[0].events[0].values.fov, 60);
  assert.equal(restored.quality.values.shadow, false);
  assert.deepEqual(restored.performers[0].transform.position, [1.25, 0, 0]);
  assert.equal(restored.soundtrack.offset, .75);
  await page.screenshot({ path: path.join(evidence, 'mv-landscape-ko.png') });
  await registrationControls(page);
}

async function timelineResize(page) {
  const grip = page.getByRole('separator', { name: '타임라인 높이' });
  const scroll = page.locator('#mv-timeline-scroll');
  const timeline = page.locator('#mv-timeline-grid');
  const clip = await timeline.locator('.mv-clip').first().elementHandle();
  const height = () => scroll.evaluate(element => element.clientHeight);
  const positions = () => page.evaluate(() => {
    const bounds = selector => document.querySelector(selector).getBoundingClientRect();
    return { top: bounds('.mv-timeline').top, bottom: bounds('.mv-timeline').bottom,
      grip: bounds('#mv-timeline-resizer').top, tools: bounds('.mv-timeline-toolbar').top,
      preview: bounds('.mv-preview').height, workspaceBottom: bounds('#mv-workspace').bottom,
      viewportBottom: innerHeight - parseFloat(getComputedStyle(document.querySelector('main')).paddingBottom) };
  });
  const near = (actual, expected) => assert(Math.abs(actual - expected) <= 1, `${actual} differs from ${expected}`);
  const before = await positions();
  const initial = await height();
  assert(initial > 62);
  near(before.bottom, before.workspaceBottom);
  near(before.bottom, before.viewportBottom);
  assert(before.grip < before.tools);
  assert.equal(await grip.getAttribute('aria-orientation'), 'horizontal');
  const rect = await grip.boundingBox();
  const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y - 24, { steps: 8 });
  await page.mouse.up();
  const dragged = initial + 24;
  assert.equal(await height(), dragged);
  const afterDrag = await positions();
  near(afterDrag.bottom, before.bottom);
  near(afterDrag.top, before.top - 24);
  near(afterDrag.grip, before.grip - 24);
  near(afterDrag.preview, before.preview - 24);
  assert.equal(await grip.getAttribute('aria-valuenow'), String(dragged));
  assert(await clip.evaluate(element => element.isConnected));
  await grip.press('ArrowUp');
  assert.equal(await height(), dragged + 16);
  await grip.press('Shift+ArrowDown');
  assert.equal(await height(), Math.max(62, dragged + 16 - 48));
  await grip.press('Shift+ArrowDown');
  assert.equal(await height(), 62);
  near((await positions()).bottom, before.bottom);
  assert(await clip.evaluate(element => element.isConnected));

  await page.locator('#mv-zoom').selectOption('96');
  await scroll.hover();
  await page.mouse.wheel(120, 120);
  await page.waitForFunction(() => {
    const pane = document.getElementById('mv-timeline-scroll');
    return pane.scrollTop > 0 && pane.scrollLeft > 0;
  });
  await grip.press('End');
  const wide = Number(await grip.getAttribute('aria-valuemax'));
  assert.equal(await height(), wide);
  const expanded = await positions();
  near(expanded.bottom, before.bottom);
  assert(expanded.preview >= 143);
  await page.reload();
  await grip.waitFor();
  assert.equal(await height(), wide);

  await page.setViewportSize({ width: 408, height: 600 });
  await page.waitForFunction(wideHeight => {
    const grip = document.getElementById('mv-timeline-resizer');
    const height = document.getElementById('mv-timeline-scroll').clientHeight;
    return height < wideHeight && height === Number(grip.getAttribute('aria-valuemax')) &&
      height === Number(grip.getAttribute('aria-valuenow'));
  }, wide);
  const portrait = await positions();
  near(portrait.bottom, portrait.workspaceBottom);
  near(portrait.bottom, portrait.viewportBottom);
  assert(portrait.preview >= 107);
  await page.setViewportSize({ width: 1180, height: 820 });
  await page.waitForFunction(expected => document.getElementById('mv-timeline-scroll').clientHeight === expected, wide);
  await grip.press('Home');
  assert.equal(await height(), 62);
  assert.equal(await scroll.evaluate(element => element.style.getPropertyValue('--mv-timeline-height')), '');
}

async function run() {
  const server = await startServer();
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ locale: 'ko', viewport: { width: 1180, height: 820 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await localAndGame(page, server.url);
    const layout = await page.locator('.mv-workspace').evaluate(element => {
      const rect = selector => element.querySelector(selector).getBoundingClientRect();
      const stage = rect('.mv-preview'), inspector = rect('.mv-inspector'), timeline = rect('.mv-timeline');
      return stage.right < inspector.left && stage.top === inspector.top && timeline.top > stage.bottom &&
        timeline.left === stage.left && timeline.right === inspector.right;
    });
    assert(layout, 'The timeline spans the preview and inspector columns');
    await timelineResize(page);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.processHandle.kill();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
