/* Render editor frames for a game-vs-editor comparison through the real MV import path.

   node tests/mv_frame_capture.js --manifest frames.json --out DIR [--url http://127.0.0.1:PORT]
     [--server-root ../] [--library SUKUSTA_DIR] [--video game.mp4] [--chromium PATH] [--software true]

   The manifest names the original MV (region, platform, liveId, assetId), the game
   quality mode and the timeline times to render. Each frame is produced with the
   game camera after a fixed-step preroll so physics has a defined history, and is
   saved as a PNG with the scene state that drew it. Nothing here reads game files
   directly: the editor's own catalog and game-stream import load the assets.

   Springs step at the reference's rate: game.exporter "fovmod" means the video is a
   FOVMOD MP4 export, which ticked the game at 60 Hz (120 Hz for 120 fps videos) with
   3*tick warm-up steps at the start pose; otherwise the game's own rule applies
   (quality frame_rate_60fps, optional manifest.device). physics.order is "game"
   (default) or "same-frame". capture.json records the rate, reference and order.

   Members follow the client's MV deck chain; source.deck "original" picks the
   Original tab instead of Customize, source.player picks a local Elichika player of
   the server root's userdata.db (default: none, a new player, even when the editor
   would preselect a lone player), and manifest.costumes pins
   {position: suit id or {suit, viewStatus}} on the import request. capture.json
   records the deck the import resolved (project.source.deck) and what each position
   wore and why (project.source.suits, project.performers).
*/
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { spawn, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const MODTOOLS = path.resolve(__dirname, '..');
// The spring frame-rate rule shared with the editor (globalThis.MVStudioPhysics).
require('../webtools/web/static/mv-studio-physics.js');
const SPRINGS = globalThis.MVStudioPhysics;

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const key = argv[index];
    if (!key.startsWith('--')) throw new Error(`Unexpected argument ${key}`);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith('--')) throw new Error(`${key} needs a value`);
    options[key.slice(2)] = value;
    index++;
  }
  if (!options.manifest || !options.out) throw new Error('Usage: --manifest FILE --out DIR [--url URL | --server-root DIR --library DIR]');
  return options;
}

// Validates the manifest and fills the defaults the comparison relies on.
function readManifest(file) {
  const manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
  const source = manifest.source || {};
  assert(['gl', 'jp'].includes(source.region), 'source.region must be gl or jp');
  assert(['android', 'ios'].includes(source.platform), 'source.platform must be android or ios');
  assert(Number.isSafeInteger(source.liveId) && Number.isSafeInteger(source.assetId), 'source.liveId and source.assetId are integers');
  const quality = manifest.quality || {};
  assert(Number.isSafeInteger(quality.mode), 'quality.mode is the game quality mode (10, 20, 30 or 40)');
  const auto = manifest.autoFrames ? { count: 6, grid: 30, margin: 0.5, ...manifest.autoFrames } : null;
  if (auto) {
    assert(Number.isSafeInteger(auto.count) && auto.count > 0 && auto.count <= 64, 'autoFrames.count is 1-64');
    assert([30, 60].includes(auto.grid), 'autoFrames.grid is the export frame rate (30 or 60)');
    assert(Number.isFinite(auto.margin) && auto.margin >= 0, 'autoFrames.margin is seconds from a camera cut');
  }
  assert(auto || (Array.isArray(manifest.frames) && manifest.frames.length), 'frames lists at least one time, or set autoFrames');
  const frames = (manifest.frames || []).map((frame) => typeof frame === 'number' ? { time: frame } : { ...frame });
  for (const frame of frames) assert(Number.isFinite(frame.time) && frame.time >= 0, 'every frame needs a time >= 0');
  const physics = manifest.physics || {};
  const preroll = physics.preroll ?? 3;
  assert(preroll === 'full' || (Number.isFinite(preroll) && preroll >= 0), 'physics.preroll is seconds or "full"');
  const order = physics.order ?? 'game';
  assert(SPRINGS.ORDERS.includes(order), 'physics.order is "game" or "same-frame"');
  const exporter = manifest.game?.exporter;
  assert(exporter === undefined || exporter === 'fovmod', 'game.exporter is "fovmod" when the reference is a FOVMOD MP4 export');
  // physics.rate: the spring grid in game frames per second when the reference is a device
  // run below its requested rate (mv_runtime_capture.gameClockRate().rate, ~4.9 at Max 3D).
  assert(physics.rate === undefined || (Number.isFinite(physics.rate) && physics.rate > 0 && physics.rate <= 120),
    'physics.rate is the game frame rate (frames per second, at most 120)');
  // screen: the device screen the game drew on; the 3D view's height follows the client rule
  // (MVStudioScene.nativeRenderHeight) for that screen instead of the preset's height.
  assert(manifest.screen === undefined || (Number.isSafeInteger(manifest.screen?.width) && Number.isSafeInteger(manifest.screen?.height) &&
    manifest.screen.width > 0 && manifest.screen.height > 0), 'screen is {width, height} in pixels');
  if (manifest.device !== undefined) SPRINGS.normalizeTiming({ device: manifest.device });
  assert(source.deck === undefined || ['custom', 'original'].includes(source.deck), 'source.deck is "custom" or "original"');
  assert(source.player === undefined || (Number.isSafeInteger(source.player) && source.player > 0),
    'source.player is a local Elichika user id');
  assert(manifest.costumes === undefined || (manifest.costumes && typeof manifest.costumes === 'object' && !Array.isArray(manifest.costumes)),
    'costumes maps positions to suit ids or {suit, viewStatus}');
  return { ...manifest, source, quality, frames, autoFrames: auto, physics: { ...physics, preroll, order } };
}

// "30/1" or "30000/1001" (ffprobe avg_frame_rate) -> frames per second.
function videoFps(rate) {
  const [num, den = '1'] = String(rate ?? '').split('/');
  const fps = Number(num) / Number(den);
  return Number.isFinite(fps) && fps > 0 ? fps : null;
}

// Which spring rate reproduces the reference. A FOVMOD MP4 export ticked the game at
// exportTickRate(fps) (60 Hz for 30 fps videos) and warmed the springs up for 3*tick
// steps at the start pose (libfovmod warmup_springs); any other reference ran the
// game's own rule, MVStudioPhysics.gameFrameRate(quality, device).
function physicsReference(manifest, qualityValues, video = null) {
  const order = manifest.physics?.order ?? 'game';
  if (manifest.game?.exporter === 'fovmod') {
    const probed = videoFps(video?.rate), stated = manifest.game.export?.fps ?? null;
    const fps = probed !== null ? Math.round(probed) : stated;
    assert(probed === null || Math.abs(probed - fps) < 1e-3, `The FOVMOD export frame rate ${video?.rate} is not a whole number`);
    assert(stated === null || stated === fps, `game.export.fps ${stated} does not match the video (${fps} fps)`);
    const rate = SPRINGS.exportTickRate(fps);
    return { source: 'fovmod-export', rate, order, exportFps: fps, device: null, warmupSteps: 3 * rate,
      timing: { order, exportFps: fps, device: {} } };
  }
  const device = manifest.device || {};
  const rate = SPRINGS.gameFrameRate(qualityValues, device);
  const reference = { source: 'game', rate, order, exportFps: null, device: manifest.device || null, warmupSteps: 0,
    timing: { order, exportFps: null, device } };
  // A device run below its requested rate stepped its springs once per frame it actually rendered:
  // the preroll grid is that rate, while the editor keeps the requested rate (ruleRate).
  return Number.isFinite(manifest.physics?.rate) ? { ...reference, source: 'manifest physics.rate', rate: manifest.physics.rate, ruleRate: rate }
    : reference;
}

// The 3D view height the client renders for a screen (LiveCoreCameraManager.Update3DCameraRenderTextures,
// MVStudioScene.nativeRenderHeight): the preset's height when no screen is known.
async function nativeRenderHeight(page, qualityValues, screenHeight) {
  if (!Number.isSafeInteger(screenHeight) || screenHeight <= 0) return qualityValues.rendering_resolution;
  return page.evaluate(({ values, screenHeight }) => MVStudioScene.nativeRenderHeight(values.rendering_resolution, screenHeight,
    values.quality_mode), { values: qualityValues, screenHeight });
}

// Camera clip boundaries of the game camera tracks, in timeline seconds.
function cameraCuts(tracks) {
  const cuts = new Set();
  for (const track of tracks) if (track.kind === 'camera' && !track.muted) {
    for (const event of track.events) { cuts.add(event.start); cuts.add(event.start + event.duration); }
  }
  return [...cuts].sort((a, b) => a - b);
}

function cutDistance(cuts, time) {
  return cuts.reduce((best, cut) => Math.min(best, Math.abs(cut - time)), Infinity);
}

// Mid-shot times spread across the song, on the export frame grid and away
// from cuts, so a one-frame timing error cannot land in a different shot.
function midShotTimes(tracks, { count, grid, margin }) {
  const cuts = cameraCuts(tracks);
  const shots = [];
  for (let index = 1; index < cuts.length; index++) {
    const start = cuts[index - 1], end = cuts[index];
    const time = Math.round((start + end) / 2 * grid) / grid;
    if (time - start >= margin && end - time >= margin) shots.push({ time, start, end });
  }
  if (shots.length <= count) return shots.map(({ time }) => time);
  return Array.from({ length: count }, (_, index) => shots[Math.floor((index + 0.5) * shots.length / count)].time);
}

function probeVideo(file) {
  const output = execFileSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries',
    'stream=width,height,avg_frame_rate', '-of', 'json', file], { encoding: 'utf8' });
  const stream = JSON.parse(output).streams?.[0];
  assert(stream && stream.width > 0 && stream.height > 0, 'The game video has no readable video stream');
  return { width: stream.width, height: stream.height, rate: stream.avg_frame_rate };
}

function gitHead(directory) {
  try { return execFileSync('git', ['-C', directory, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(); } catch (_) { return null; }
}

function gitDirty(directory) {
  try { return execFileSync('git', ['-C', directory, 'status', '--porcelain'], { encoding: 'utf8' }).trim().length > 0; } catch (_) { return null; }
}

async function freePort() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  return port;
}

async function bootEditor(serverRoot, library, logFile) {
  const port = await freePort();
  const log = fs.openSync(logFile, 'w');
  const env = { ...process.env, PYTHONPATH: [MODTOOLS, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) };
  if (library) env.SUKUSTA_DIR = library;
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)],
    { cwd: serverRoot, env, stdio: ['ignore', log, log] });
  fs.closeSync(log);
  const url = 'http://127.0.0.1:' + port;
  for (let tries = 0; tries < 200; tries++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { child, url }; } catch (_) {}
    if (child.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  child.kill();
  throw new Error(`The MV editor did not start; see ${logFile}`);
}

// Keeps the scene the editor creates so frames can be stepped and inspected.
function attachSceneProbe() {
  const probe = window.mvFrameProbe = { scene: null };
  let factory;
  Object.defineProperty(window, 'MVStudioScene', {
    configurable: true,
    get() { return factory; },
    set(value) {
      factory = { ...value, create(...options) {
        const scene = value.create(...options);
        probe.scene = scene;
        return scene;
      } };
    },
  });
}

// The deck tab (1 Original, 2 Customize, the client's first tab) and local player a
// manifest source asks for; userId null is a new player.
function deckRequest(source) {
  return { deckType: source.deck === 'original' ? 1 : 2, userId: source.player ?? null };
}

async function importOriginal(page, source, download) {
  await page.waitForFunction(() => window.MVStudio && MVStudio.getState().visible);
  await page.locator('#mv-import-game').click();
  const choose = async (selector, value) => {
    await page.waitForFunction(({ selector, value }) =>
      [...document.querySelector(selector).options].some(option => option.value === value), { selector, value }, { timeout: 60000 });
    await page.selectOption(selector, value);
  };
  await choose('#mv-game-region', source.region);
  await choose('#mv-game-platform', source.platform);
  await choose('#mv-game-song', String(source.liveId));
  await choose('#mv-game-variant', String(source.assetId));
  const deck = deckRequest(source);
  await page.selectOption('#mv-game-deck', String(deck.deckType));
  // A catalog reload still in flight re-syncs the variants and clears the download box when it
  // ends; the load button stays disabled until then.
  await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled, null, { timeout: 60000 });
  // The editor preselects a lone player of the server's userdata.db; always choose explicitly.
  const player = deck.userId === null ? '' : String(deck.userId);
  const players = await page.evaluate(() => [...document.querySelector('#mv-game-player').options].map((option) => option.value));
  if (!players.includes(player)) {
    throw new Error(`Player ${deck.userId} is not in the editor server's player database (offered: ${players.filter(Boolean).join(', ') || 'none'})`);
  }
  // Set directly: the player field is hidden when the server has no player database.
  await page.evaluate((value) => {
    const select = document.querySelector('#mv-game-player');
    select.value = value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }, player);
  await page.locator('#mv-game-download').setChecked(Boolean(download));
  await page.locator('#mv-game-load').click();
  // The import operation disables the button synchronously and re-enables it when it ends.
  await page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled, null, { timeout: 30 * 60 * 1000, polling: 500 });
  const result = await page.evaluate(() => ({ source: MVStudio.getState().project?.source || null,
    status: document.querySelector('#mv-status')?.textContent?.trim() || '' }));
  const imported = result.source || {};
  if (imported.kind !== 'game' || imported.liveId !== source.liveId || imported.assetId !== source.assetId ||
      imported.region !== source.region || imported.platform !== source.platform) {
    throw new Error(`The editor did not import ${source.region}/${source.platform} ${source.liveId}/${source.assetId}` +
      (result.status ? `: ${result.status}` : '') + ` (imported ${JSON.stringify(result.source)})`);
  }
  const resolved = imported.deck || {};
  if (resolved.deckType !== deck.deckType || (resolved.userId ?? null) !== deck.userId) {
    throw new Error(`The editor dressed the members from deck ${JSON.stringify(imported.deck ?? null)}, not ${JSON.stringify(deck)}`);
  }
  return imported;
}

// The imported project as capture.json records it: what was loaded, and per position the
// suit worn, its view status, attach key and why (suitSource deck / mapping / memberInit /
// nonPlayable / pinned).
async function projectRecord(page) {
  return page.evaluate(() => {
    const value = MVStudio.getState().project;
    return { name: value.name, source: value.source, duration: value.duration, warnings: value.warnings || [],
      soundtrack: value.soundtrack ? { url: value.soundtrack.url, offset: value.soundtrack.offset ?? 0 } : null,
      importCoverage: value.importCoverage ?? null,
      performers: (value.performers || []).map((item) => ({ position: item.position ?? null, memberId: item.memberId ?? null,
        costumeId: item.costumeId ?? null, viewStatus: item.viewStatus ?? null, suitSource: item.suitSource ?? null,
        attachKey: item.attachKey || '', loaded: typeof item.glb === 'string' && item.glb.length > 0 })) };
  });
}

async function applyQuality(page, quality) {
  const applied = await page.evaluate(({ mode, overrides }) => {
    const select = document.querySelector('#mv-quality-mode');
    if (!select || ![...select.options].some(option => option.value === String(mode))) return { error: `Quality mode ${mode} is not offered by this stage.` };
    select.value = String(mode);
    select.dispatchEvent(new Event('change', { bubbles: true }));
    for (const [key, value] of Object.entries(overrides || {})) {
      const input = document.querySelector(`[data-mv-quality="${key}"]`);
      if (!input) return { error: `Quality value ${key} has no editor control.` };
      if (input.type === 'checkbox') input.checked = Boolean(value); else input.value = String(value);
      input.dispatchEvent(new Event(input.type === 'checkbox' ? 'change' : 'input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    const project = MVStudio.getState().project;
    return { mode: project.quality.mode, values: project.quality.values };
  }, quality);
  if (applied.error) throw new Error(applied.error);
  assert.equal(applied.mode, quality.mode, 'The editor did not apply the requested quality mode');
  for (const [key, value] of Object.entries(quality.overrides || {})) assert.deepEqual(applied.values[key], value, `Quality value ${key} was not applied`);
  return applied;
}

// Pins the preview mount to the game's aspect at the native render height.
async function pinViewport(page, width, height) {
  await page.evaluate(({ width, height }) => {
    const mount = document.querySelector('#mv-scene');
    Object.assign(mount.style, { position: 'fixed', left: '0', top: '0', width: width + 'px', height: height + 'px', zIndex: '2147483646' });
  }, { width, height });
  await page.waitForFunction(({ width, height }) => {
    const mount = document.querySelector('#mv-scene');
    return mount.clientWidth === width && mount.clientHeight === height;
  }, { width, height });
}

// Fixed-step playback on a grid that ends exactly at `time`, then one
// synchronous draw and readback. Physics advances once per stepped frame.
// When the preroll reaches the song start, `warmup` extra frames are first
// played at the start pose (FOVMOD warmup_springs).
async function renderFrame(page, time, preroll, rate, warmup = 0) {
  return page.evaluate(({ time, preroll, rate, warmup }) => {
    const scene = mvFrameProbe.scene;
    const available = Math.floor(time * rate + 1e-6);
    const steps = preroll === 'full' ? available : Math.min(available, Math.floor(preroll * rate + 1e-6));
    const start = time - steps / rate;
    const warm = steps === available ? warmup : 0;
    scene.resize(false);
    // The editor's own seek path resets physics only when the time changes.
    if (Math.abs(scene.inspect().time - start) <= 1e-9) scene.seek(start + 1 / rate, undefined, true);
    scene.seek(start, undefined, true);
    scene.setPlaying(true);
    try {
      for (let step = 0; step < warm; step++) scene.playbackFrame(start, step * 1000 / rate, true);
      for (let step = 0; step < steps; step++) scene.playbackFrame(start + step / rate, (warm + step) * 1000 / rate, true);
      // A grid slower than 25 Hz (a device run's achieved rate, e.g. ~4.9 fps at Max 3D) trips
      // the playback's slow-frame preview downscale, which would draw this frame below the
      // pinned size: restart playback so the preview scale returns to 1 (the physics clock
      // still steps once on the drawn frame).
      const previewRestored = (scene.inspect().previewScale ?? 1) !== 1;
      if (previewRestored) { scene.setPlaying(false); scene.setPlaying(true); }
      scene.playbackFrame(time, (warm + steps) * 1000 / rate, false);
      const canvas = document.querySelector('#mv-scene canvas');
      const png = canvas.toDataURL('image/png');
      return { png, state: scene.inspect(), steps, warmupSteps: warm, prerollStart: start, previewRestored };
    } finally {
      scene.setPlaying(false);
    }
  }, { time, preroll, rate, warmup });
}

// Applies the reference's spring timing to the scene and returns what it applied.
async function applyPhysicsReference(page, reference) {
  const applied = await page.evaluate((timing) => mvFrameProbe.scene.setPhysicsTiming(timing), reference.timing);
  assert(applied, 'The editor scene has no spring timing control');
  assert.equal(applied.rate, reference.ruleRate ?? reference.rate, 'The editor did not apply the reference spring rate');
  assert.equal(applied.order, reference.order, 'The editor did not apply the reference spring order');
  return applied;
}

async function rendererInfo(page) {
  return page.evaluate(() => {
    const gl = document.querySelector('#mv-scene canvas')?.getContext('webgl2');
    const debug = gl?.getExtension('WEBGL_debug_renderer_info');
    return debug ? { vendor: gl.getParameter(debug.UNMASKED_VENDOR_WEBGL), renderer: gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) } :
      { vendor: gl?.getParameter(gl.VENDOR) ?? null, renderer: gl?.getParameter(gl.RENDERER) ?? null };
  });
}

// Hardware WebGL by default so a Mac capture uses its GPU; --software true forces SwiftShader.
function browserArgs(software) {
  return ['--no-sandbox', '--disable-dev-shm-usage', '--enable-unsafe-swiftshader', ...(software ? ['--disable-gpu'] : [])];
}

function frameName(time) {
  return 'editor-' + time.toFixed(4).replace('.', '_') + '.png';
}

async function run() {
  const options = parseArgs(process.argv.slice(2));
  const manifest = readManifest(options.manifest);
  const out = path.resolve(options.out);
  fs.mkdirSync(out, { recursive: true });
  const video = options.video ? path.resolve(options.video) :
    manifest.game?.video ? path.resolve(path.dirname(options.manifest), manifest.game.video) : null;
  const target = video ? probeVideo(video) : null;
  const aspect = target ? target.width / target.height : (manifest.aspect ?? 16 / 9);
  const serverRoot = path.resolve(options['server-root'] || path.join(MODTOOLS, '..'));
  let server = null, browser = null;
  try {
    const url = options.url || (server = await bootEditor(serverRoot, options.library, path.join(out, 'editor-server.log'))).url;
    browser = await chromium.launch({ executablePath: options.chromium || process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: browserArgs(options.software === 'true') });
    const page = await browser.newPage({ viewport: { width: 2600, height: 1600 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(attachSceneProbe);
    await page.goto(url + '/#mv');
    if (manifest.costumes) {
      // The import request carries the pinned costumes (server option `costumes`).
      await page.route(/\/api\/mv-studio\/game(?:-stream)?(?:\?|$)/, async (route) => {
        const request = route.request();
        if (request.method() !== 'POST') return route.continue();
        const body = JSON.parse(request.postData() || '{}');
        return route.continue({ postData: JSON.stringify({ ...body, costumes: manifest.costumes }) });
      });
    }
    await importOriginal(page, manifest.source, manifest.download === true);
    const quality = await applyQuality(page, manifest.quality);
    // The game draws at the client's height for its screen (manifest.screen, else the video's
    // height; the preset's height when neither is known); the export then scales to the video size.
    const renderHeight = await nativeRenderHeight(page, quality.values, manifest.screen?.height ?? target?.height);
    const renderWidth = Math.round(renderHeight * aspect / 2) * 2;
    await pinViewport(page, renderWidth, renderHeight);
    await page.evaluate((screenFade) => {
      const select = document.querySelector('#mv-camera-mode');
      select.value = 'live';
      select.dispatchEvent(new Event('change', { bubbles: true }));
      // The MV dark filter and live-end blur are absent from the libfovmod 3D
      // captures this harness is compared with; a manifest can ask for them.
      const fade = document.querySelector('#mv-screen-fade');
      if (fade && fade.checked !== screenFade) {
        fade.checked = screenFade;
        fade.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }, manifest.screenFade === true);
    const physics = physicsReference(manifest, quality.values, target);
    await applyPhysicsReference(page, physics);
    const rate = physics.rate;
    const project = await projectRecord(page);
    let soundtrack = null;
    if (project.soundtrack?.url) {
      const response = await page.request.get(new URL(project.soundtrack.url, url).href);
      if (response.ok()) {
        soundtrack = 'soundtrack' + (path.extname(new URL(project.soundtrack.url, url).pathname) || '.wav');
        fs.writeFileSync(path.join(out, soundtrack), await response.body());
      }
    }
    const tracks = await page.evaluate(() => MVStudio.getState().project.tracks
      .filter(track => track.kind === 'camera').map(({ kind, muted, events }) => ({ kind, muted,
        events: events.map(({ start, duration }) => ({ start, duration })) })));
    const cuts = cameraCuts(tracks);
    const planned = manifest.autoFrames ? midShotTimes(tracks, manifest.autoFrames).map(time => ({ time, label: 'auto mid-shot' })) : [];
    const wanted = [...manifest.frames, ...planned.filter(auto => !manifest.frames.some(frame => Math.abs(frame.time - auto.time) < 1e-6))];
    const frames = [];
    for (const frame of wanted.sort((a, b) => a.time - b.time)) {
      const { png, state, steps, warmupSteps, prerollStart } = await renderFrame(page, frame.time, manifest.physics.preroll, rate,
        physics.warmupSteps);
      const file = frameName(frame.time);
      fs.writeFileSync(path.join(out, file), Buffer.from(png.slice(png.indexOf(',') + 1), 'base64'));
      assert.equal(state.canvas.width, renderWidth, 'The editor canvas width does not match the requested render size');
      assert.equal(state.canvas.height, renderHeight, 'The editor canvas height does not match the requested render size');
      frames.push({ ...frame, image: file, prerollStart, physicsSteps: steps, warmupSteps, cutDistance: cutDistance(cuts, frame.time), state });
    }
    const capture = {
      schema: 1, kind: 'elichika-mv-editor-frames', createdAt: new Date().toISOString(),
      manifest, project, soundtrack, physicsRate: rate,
      physics: { rate, reference: physics.source, order: physics.order, exportFps: physics.exportFps, device: physics.device,
        warmupSteps: physics.warmupSteps },
      render: { width: renderWidth, height: renderHeight, aspect, video: target },
      quality: { mode: quality.mode, values: quality.values },
      environment: {
        modtools: { commit: gitHead(MODTOOLS), dirty: gitDirty(MODTOOLS) },
        server: { root: serverRoot, commit: options.url ? null : gitHead(serverRoot) },
        url: options.url || null, browser: browser.version(), webgl: await rendererInfo(page), platform: process.platform,
      },
      pageErrors: errors, frames,
    };
    fs.writeFileSync(path.join(out, 'capture.json'), JSON.stringify(capture, null, 2) + '\n');
    console.log(JSON.stringify({ out, frames: frames.length, webgl: capture.environment.webgl, warnings: project.warnings.length, pageErrors: errors.length }));
  } finally {
    if (browser) await browser.close();
    if (server) server.child.kill();
  }
}

if (require.main === module) run().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
module.exports = { readManifest, frameName, cameraCuts, cutDistance, midShotTimes, attachSceneProbe, deckRequest, importOriginal, projectRecord, applyQuality, pinViewport, renderFrame, rendererInfo, browserArgs, bootEditor, gitHead, gitDirty,
  videoFps, physicsReference, applyPhysicsReference };
