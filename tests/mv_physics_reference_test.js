/* Which spring rate the comparison harnesses use for a reference (no browser).
   A FOVMOD MP4 export ticked the game at 60 Hz (120 Hz for 120 fps) with 3*tick
   warm-up steps; a real-time runtime dump ran at the frame rate the game achieved;
   anything else follows the game's own rule. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const capture = require('./mv_frame_capture');
const runtime = require('./mv_runtime_capture');
const check = require('./mv_spring_order_check');

const base = {
  source: { region: 'gl', platform: 'android', liveId: 12035, assetId: 1203503 }, quality: { mode: 30 }, frames: [14.85],
};
function manifest(extra) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-physics-'));
  try {
    const file = path.join(folder, 'manifest.json');
    fs.writeFileSync(file, JSON.stringify({ ...base, ...extra }));
    return capture.readManifest(file);
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
}
const q30 = { frame_rate_60fps: false }, q10 = { frame_rate_60fps: true };

// mv_spring_order_check: a scaled bone's decomposed rotation is not a unit quaternion.
assert(check.angle([0, 0, .3826834 * .998, .9238795 * .998], [0, 0, .3826834, .9238795]) < 1e-4, "scale is not an angle");
assert(Math.abs(check.angle([0, 0, 0, 1], [0, 0, Math.sin(Math.PI / 36), Math.cos(Math.PI / 36)]) - 10) < 1e-9);
assert.deepEqual(check.parseConfig('game@60'), { name: 'game@60', order: 'game', grid: 60 });
assert.throws(() => check.parseConfig('lagged'), /order is game or same-frame/);

assert.equal(capture.videoFps('30/1'), 30);
assert.equal(capture.videoFps('120/1'), 120);
assert(Math.abs(capture.videoFps('30000/1001') - 29.97) < 1e-2);
assert.equal(capture.videoFps('0/0'), null);
assert.equal(capture.videoFps(undefined), null);

// Real-time game rule: Normal 3D at 30 Hz, Max 3D at 60 Hz, CoolAssist and refresh-rate mode.
let reference = capture.physicsReference(manifest({}), q30);
assert.deepEqual([reference.source, reference.rate, reference.order, reference.warmupSteps], ['game', 30, 'game', 0]);
assert.equal(capture.physicsReference(manifest({}), q10).rate, 60);
assert.equal(capture.physicsReference(manifest({ device: { coolAssist: true } }), q10).rate, 30);
assert.equal(capture.physicsReference(manifest({ device: { refreshRateMode: true, displayRate: 90 } }), q30).rate, 90);
assert.throws(() => manifest({ device: { refreshRateMode: true, displayRate: 75 } }), /60, 90 or 120/);
assert.equal(manifest({ physics: { order: 'same-frame' } }).physics.order, 'same-frame');
assert.throws(() => manifest({ physics: { order: 'late' } }), /physics.order/);
assert.throws(() => manifest({ game: { exporter: 'obs' } }), /game.exporter/);

// A device run below its requested rate: the preroll grid is the rate it achieved, the editor
// keeps the requested rate; a FOVMOD export keeps its tick rule.
reference = capture.physicsReference(manifest({ physics: { rate: 4.87 } }), q10);
assert.deepEqual([reference.source, reference.rate, reference.ruleRate], ['manifest physics.rate', 4.87, 60]);
assert.throws(() => manifest({ physics: { rate: 0 } }), /physics.rate/);
assert.throws(() => manifest({ screen: { width: 1280 } }), /screen is/);
assert.deepEqual(manifest({ screen: { width: 1280, height: 720 } }).screen, { width: 1280, height: 720 });
// device.antiAliasing: the player's option, a boolean; it does not change the spring rate.
assert.equal(manifest({ device: { antiAliasing: true } }).device.antiAliasing, true);
assert.throws(() => manifest({ device: { antiAliasing: 1 } }), /device.antiAliasing/);
assert.equal(capture.physicsReference(manifest({ device: { antiAliasing: true } }), q10).rate, 60);

// FOVMOD exports: grid 60 for a 30 fps MP4 (frames still land on k/30), 120 for 120 fps.
const fovmod = manifest({ game: { exporter: 'fovmod', video: 'x.mp4', export: { fps: 30 } } });
reference = capture.physicsReference(fovmod, q30, { rate: '30/1' });
assert.deepEqual([reference.source, reference.rate, reference.exportFps, reference.warmupSteps], ['fovmod-export', 60, 30, 180]);
assert.deepEqual(reference.timing, { order: 'game', exportFps: 30, device: {} });
assert.equal(capture.physicsReference(fovmod, q10, null).rate, 60, 'the stated export fps is used without a probed video');
assert.equal(capture.physicsReference(manifest({ game: { exporter: 'fovmod' } }), q30, { rate: '120/1' }).rate, 120);
assert.throws(() => capture.physicsReference(fovmod, q30, { rate: '60/1' }), /does not match/);
assert.throws(() => capture.physicsReference(manifest({ game: { exporter: 'fovmod' } }), q30, { rate: '25/1' }), /30, 60 or 120/);
assert.throws(() => capture.physicsReference(manifest({ game: { exporter: 'fovmod' } }), q30, { rate: '30000/1001' }), /whole number/);

// `node tests/mv_frame_capture.js --game-dump` reads the dump (requiring mv_runtime_capture.js, which
// requires the runner back) before it applies the game's quality: the runner must be fully exported by
// then. A preloaded playwright stand-in applies a quality through mv_runtime_capture.js from inside
// chromium.launch(), the first step after the dump is read, and stops the run there.
function commandLineGameDump() {
  const { spawnSync } = require('node:child_process');
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-physics-cli-'));
  try {
    const dump = path.join(folder, 'dump.json'), file = path.join(folder, 'manifest.json'), stub = path.join(folder, 'stub.js');
    fs.writeFileSync(dump, JSON.stringify({ schema: runtime.SCHEMA, side: 'game', header: {},
      records: [10, 11].map((frameCount) => ({ id: `f${frameCount}`, kind: 'frame', clock: { frameCount, directorTime: frameCount / 10, deltaTime: 0.1 } })) }));
    fs.writeFileSync(file, JSON.stringify(base));
    fs.writeFileSync(stub, `'use strict';
const Module = require('node:module');
const load = Module._load;
Module._load = function (request, ...rest) {
  if (request !== 'playwright') return load.call(this, request, ...rest);
  return { chromium: { async launch() {
    const runtime = require(${JSON.stringify(path.join(__dirname, 'mv_runtime_capture.js'))});
    const page = { evaluate: async (fn, args) => args === undefined ? { modes: [30], options: [] } : { mode: 30, values: {} } };
    const applied = await runtime.applyGameQuality(page, undefined, { mode: 30 });
    console.log('STUB_QUALITY ' + applied.mode);
    throw new Error('stub browser stops here');
  } } };
};
`);
    const result = spawnSync(process.execPath, ['-r', stub, path.join(__dirname, 'mv_frame_capture.js'), '--manifest', file,
      '--out', path.join(folder, 'out'), '--url', 'http://127.0.0.1:9', '--game-dump', dump], { encoding: 'utf8' });
    assert.match(result.stdout, /STUB_QUALITY 30/, result.stderr);
    assert.match(result.stderr, /stub browser stops here/);
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
}

// renderFrame: warm-up frames at the start pose only when the preroll reaches the song start.
function fakePage() {
  const calls = [];
  globalThis.document = { querySelector: () => ({ toDataURL: () => 'data:image/png;base64,' }) };
  globalThis.mvFrameProbe = { scene: {
    time: -1, resize() { calls.push(['resize']); }, inspect() { return { time: this.time }; },
    setAdaptivePreview(value) { calls.push(['adaptive', value]); },
    seek(time) { this.time = time; calls.push(['seek', time]); }, setPlaying(value) { calls.push(['playing', value]); },
    playbackFrame(time, stamp, deferred) { this.time = time; calls.push(['frame', time, stamp, deferred]); },
  } };
  return { calls, evaluate: async (fn, args) => fn(args) };
}
(async () => {
  // The render height follows the client rule with the manifest's anti-aliasing option, and the
  // option is set through the editor's control (off unless the manifest turns it on).
  const heights = [];
  globalThis.MVStudioScene = { nativeRenderHeight: (...args) => { heights.push(args); return args[3] ? args[1] : Math.min(args[0], args[1]); } };
  const direct = { evaluate: async (fn, args) => fn(args) };
  const max3d = { quality_mode: 10, rendering_resolution: 1080 };
  assert.equal(await capture.nativeRenderHeight(direct, max3d, 1440), 1080);
  assert.equal(await capture.nativeRenderHeight(direct, max3d, 1440, true), 1440);
  assert.equal(await capture.nativeRenderHeight(direct, max3d, undefined, true), 1080, 'no screen: the preset height');
  assert.deepEqual(heights, [[1080, 1440, 10, false], [1080, 1440, 10, true]]);
  const control = { checked: false, events: [], dispatchEvent(event) { this.events.push(event.type); } };
  let sceneAntiAliasing = false;
  globalThis.Event = class { constructor(type) { this.type = type; } };
  globalThis.document = { querySelector: (selector) => selector === '#mv-anti-aliasing' ? control : null };
  globalThis.mvFrameProbe = { scene: { inspect: () => ({ antiAliasing: sceneAntiAliasing }) } };
  assert.equal(await capture.applyAntiAliasing(direct, undefined), false);
  assert.deepEqual(control.events, [], 'off by default: the control is left alone');
  control.dispatchEvent = function (event) { this.events.push(event.type); sceneAntiAliasing = this.checked; };
  assert.equal(await capture.applyAntiAliasing(direct, true), true);
  assert.deepEqual([control.checked, control.events], [true, ['change']]);
  control.dispatchEvent = function (event) { this.events.push(event.type); };
  control.checked = false;
  sceneAntiAliasing = false;
  await assert.rejects(capture.applyAntiAliasing(direct, true), /did not apply the anti-aliasing option/);
  // A project without quality options has no control: off is checked on the scene, on is refused.
  globalThis.document = { querySelector: () => null };
  sceneAntiAliasing = false;
  assert.equal(await capture.applyAntiAliasing(direct, false), false);
  assert.equal(await capture.applyAntiAliasing(direct, undefined), false);
  await assert.rejects(capture.applyAntiAliasing(direct, true), /no anti-aliasing control/);
  sceneAntiAliasing = true;
  await assert.rejects(capture.applyAntiAliasing(direct, false), /did not apply the anti-aliasing option/,
    'without the control a scene that draws with the option on is still caught');
  globalThis.mvFrameProbe = { scene: null };
  await assert.rejects(capture.applyAntiAliasing(direct, false), /did not apply the anti-aliasing option/, 'no scene to check');
  delete globalThis.MVStudioScene;

  let page = fakePage();
  let result = await capture.renderFrame(page, 1, 3, 60, 180);
  const frames = page.calls.filter(([kind]) => kind === 'frame');
  assert.equal(result.warmupSteps, 180);
  assert.equal(result.steps, 60);
  assert.equal(frames.length, 180 + 60 + 1);
  assert(frames.slice(0, 180).every(([, time]) => time === 0), 'warm-up frames hold the start pose');
  assert(frames.every(([, , stamp], index) => Math.abs(stamp - index * 1000 / 60) < 1e-9), 'one clock interval per frame');
  assert.deepEqual(frames.at(-1).slice(1), [1, 240 * 1000 / 60, false]);
  page = fakePage();
  result = await capture.renderFrame(page, 14.85, 3, 60, 180);
  assert.equal(result.warmupSteps, 0, 'a preroll that starts mid-song has no warm-up');
  assert.equal(page.calls.filter(([kind]) => kind === 'frame').length, 181);
  assert.equal(result.prerollStart, 14.85 - 3);

  // A 4.87 Hz device grid would trip the playback's slow-frame preview downscale: the capture
  // turns the adaptive preview off before the preroll and keeps playing through the drawn frame
  // (no playback restart, which would reset the physics and shaft damping clocks).
  page = fakePage();
  result = await capture.renderFrame(page, 49.649, 3, 4.87);
  const kinds = page.calls.map(([kind]) => kind);
  assert.deepEqual(page.calls[0], ['adaptive', false], 'the adaptive preview is off before anything is evaluated');
  assert.equal(kinds.indexOf('resize'), 1);
  const played = page.calls.filter(([kind]) => kind === 'playing');
  assert.deepEqual(played, [['playing', true], ['playing', false]], 'playback starts once and stops after the drawn frame');
  const first = kinds.indexOf('frame'), drawn = kinds.lastIndexOf('frame');
  assert(kinds.indexOf('playing') < first && kinds.lastIndexOf('playing') > drawn, 'every frame, the drawn one included, plays in one run');
  assert.deepEqual(page.calls.at(-1), ['adaptive', true], 'the editor gets its adaptive preview back');
  assert.equal(page.calls[drawn][3], false, 'the drawn frame is not deferred');
  assert.equal(Math.round(page.calls[drawn][1] * 1e3) / 1e3, 49.649);
  page = fakePage();
  globalThis.mvFrameProbe.scene.setAdaptivePreview = undefined;
  await assert.rejects(capture.renderFrame(page, 1, 3, 60), /setAdaptivePreview/);

  // A game frame grid (--game-dump or manifest physics.grid): the springs preroll on the game's own
  // frames inside the window. Each stamp advances by the frame's Time.deltaTime (clamped to 1/3 s)
  // and at least one spring-clock interval, so the springs step once per game frame.
  const gameGrid = [45.9, 46.1, 46.3, 46.8, 47.4, 47.6, 47.6, 47.81, 48.02, 48.2, 48.4, 48.6, 48.8, 49.0, 49.2, 49.4, 49.649, 49.85];
  page = fakePage();
  result = await capture.renderFrame(page, 49.649, 3, 4.87, 0, gameGrid, 60);
  const gridFrames = page.calls.filter(([kind]) => kind === 'frame');
  assert.deepEqual([result.prerollSource, result.steps, result.warmupSteps, result.prerollStart], ['game-frames', 13, 0, 46.8]);
  assert.deepEqual(gridFrames.slice(0, -1).map(([, time]) => time), gameGrid.slice(3, 16), 'the game frames inside [t - 3 s, t)');
  assert(gridFrames.slice(0, -1).every((call) => call[3] === true), 'preroll frames are deferred');
  assert.deepEqual(gridFrames.at(-1).slice(1, 2).concat(gridFrames.at(-1)[3]), [49.649, false], 'then the drawn frame');
  const intervals = gridFrames.slice(1).map(([, , stamp], index) => Math.round((stamp - gridFrames[index][2]) * 1e3) / 1e3);
  assert.deepEqual(intervals.slice(0, 4), [333.333, 200, 16.667, 210],
    'clamped at 1/3 s; a repeated (pinned) time still steps one spring-clock interval');
  assert.equal(intervals.at(-1), 249, 'the drawn frame follows the last game frame by its own interval');
  assert.equal(gridFrames[0][2], 0);
  // A window the grid does not cover keeps the fixed-rate grid.
  assert.equal((await capture.renderFrame(fakePage(), 10, 3, 4.87, 0, gameGrid, 60)).prerollSource, 'fixed-rate');
  assert.equal(capture.prerollPlan(49.649, 3, 4.87).source, 'fixed-rate');
  // The grid comes from manifest physics.grid or a runtime dump, never both.
  assert.deepEqual(manifest({ physics: { grid: [1, 1.2, 1.2] } }).physics.grid, [1, 1.2, 1.2]);
  assert.throws(() => manifest({ physics: { grid: [1.2, 1] } }), /physics.grid/);
  assert.throws(() => manifest({ physics: { grid: [1] }, game: { exporter: 'fovmod' } }), /physics.grid is for a real-time game run/);
  assert.deepEqual(capture.gameFrameGrid(manifest({ physics: { grid: [1, 2] } })), { source: 'manifest physics.grid', file: null, times: [1, 2] });
  assert.equal(capture.gameFrameGrid(manifest({})), null);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-grid-'));
  try {
    const file = path.join(folder, 'dump.json');
    const frame = (frameCount, directorTime, deltaTime) => ({ id: `f${frameCount}`, kind: 'frame', clock: { frameCount, directorTime, deltaTime } });
    fs.writeFileSync(file, JSON.stringify({ schema: runtime.SCHEMA, side: 'game', header: {},
      records: [frame(100, 10, .2), frame(102, 10.5, .25), frame(103, 10.7, .2)] }));
    assert.deepEqual(capture.gameFrameGrid(manifest({}), file), { source: 'game-dump', file: 'dump.json', times: [10, 10.25, 10.5, 10.7] });
    assert.throws(() => capture.gameFrameGrid(manifest({ physics: { grid: [1] } }), file), /not both/);
    const read = capture.readGameDump(file);
    assert.equal(read.file, 'dump.json');
    assert.deepEqual(capture.gameFrameGrid(manifest({}), read).times, [10, 10.25, 10.5, 10.7], 'a dump read once gives the same grid');
    const editorFile = path.join(folder, 'editor.json');
    fs.writeFileSync(editorFile, JSON.stringify({ schema: runtime.SCHEMA, side: 'editor', header: {}, records: [] }));
    assert.throws(() => capture.readGameDump(editorFile), /must be a game runtime dump/);
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }

  // With --game-dump the frames are drawn at the quality the game ran (header.quality, as the value
  // capture applies it), so the spring clock's rule rate follows the game run: dump3b ran Max 3D with
  // FrameRate60Fps false, while the editor's Max 3D preset has frame_rate_60fps true.
  const presets = { 10: { rendering_resolution: 1080, frame_rate_60fps: true, posteffect: true },
    30: { rendering_resolution: 720, frame_rate_60fps: false, posteffect: true } };
  const options = [{ key: 'rendering_resolution', type: 'number' }, { key: 'frame_rate_60fps', type: 'boolean' },
    { key: 'posteffect', type: 'boolean' }];
  const editorProject = { quality: { mode: 30, values: { quality_mode: 30, ...presets[30] }, modes: [{ id: 10 }, { id: 30 }], options } };
  const modeSelect = { options: [{ value: '10' }, { value: '30' }], value: '30',
    dispatchEvent() { editorProject.quality.mode = Number(this.value); editorProject.quality.values = { quality_mode: Number(this.value), ...presets[this.value] }; } };
  const inputs = Object.fromEntries(options.map(({ key, type }) => [key, { type: type === 'boolean' ? 'checkbox' : 'number', checked: false, value: '',
    dispatchEvent(event) { if (event.type === 'change') editorProject.quality.values[key] = type === 'boolean' ? this.checked : Number(this.value); } }]));
  globalThis.MVStudio = { getState: () => ({ project: editorProject }) };
  globalThis.document = { querySelector: (selector) => selector === '#mv-quality-mode' ? modeSelect
    : inputs[/data-mv-quality="(\w+)"/.exec(selector)?.[1]] ?? null };
  const max3d10 = manifest({ quality: { mode: 10 }, physics: { rate: 4.869 } });
  const gameRun = { file: 'mv-runtime-dump.json.gz', doc: { side: 'game', header: { quality: { values: { Quality: { v: 10, n: null },
    RenderingResolution: 1080, FrameRate60Fps: false, RefreshRateMode: false, PostEffect: true } } } } };
  let quality = await capture.captureQuality(direct, max3d10, gameRun);
  assert.deepEqual([quality.source, quality.status, quality.mode, quality.values.frame_rate_60fps], ['game', 'matched', 10, false]);
  assert.deepEqual(quality.request, { mode: 10, overrides: { rendering_resolution: 1080, frame_rate_60fps: false, posteffect: true } });
  assert.deepEqual(quality.gameOnly, ['RefreshRateMode']);
  reference = capture.physicsReference(max3d10, quality.values);
  assert.deepEqual([reference.rate, reference.ruleRate], [4.869, 30], 'the spring clock runs at the rate the game requested');
  // Without the dump the manifest's preset decides (60 Hz at Max 3D).
  quality = await capture.captureQuality(direct, max3d10);
  assert.deepEqual([quality.source, quality.mode, quality.values.frame_rate_60fps], ['manifest', 10, true]);
  assert.equal(capture.physicsReference(max3d10, quality.values).ruleRate, 60);
  // A dump that recorded no quality falls back to the manifest quality and says so.
  quality = await capture.captureQuality(direct, max3d10, { file: 'old.json', doc: { side: 'game', header: {} } });
  assert.deepEqual([quality.source, quality.status, quality.mode, quality.values.frame_rate_60fps], ['manifest', 'invalid:quality', 10, true]);
  assert.deepEqual(quality.reasons, ['the game dump records no quality values']);
  delete globalThis.MVStudio;
  commandLineGameDump();

  // Real-time runtime dumps step at the achieved frame rate, capped by the requested rate.
  const clock = (directorTime, frameCount, deltaTime = .1) => ({ clock: { directorTime, frameCount, deltaTime } });
  const slow = { records: [clock(0, 900), clock(1, 1000), clock(3, 1021), clock(5, 1042), clock(10, 1100), clock(10, 1104)] };
  let rate = runtime.gameClockRate(slow, q30);
  assert.equal(rate.source, 'game-clock');
  assert.equal(rate.target, 30);
  assert(Math.abs(rate.rate - 21 / 2) < 1e-12, 'frames per director second while the director advances');
  assert(Math.abs(rate.meanDeltaTime - .1) < 1e-12);
  // A synthetic document counts records, not frames: its deltaTime gives the rate.
  const synthetic = { records: [clock(11.5, 1000, 1 / 20), clock(14.85, 1001, 1 / 20), clock(50.3, 1002, 1 / 20), clock(97, 1003, 1 / 20)] };
  rate = runtime.gameClockRate(synthetic, q30);
  assert.equal(rate.source, 'game-deltaTime');
  assert(Math.abs(rate.rate - 20) < 1e-9);
  const fast = { records: [clock(1, 0, .005), clock(2, 200, .005), clock(3, 400, .005)] };
  assert.equal(runtime.gameClockRate(fast, q10).rate, 60, 'never faster than the requested rate');
  rate = runtime.gameClockRate({ records: [clock(0, 1), clock(0, 2)] }, q30);
  assert.deepEqual([rate.source, rate.rate], ['game-rule', 30]);
  console.log('MV comparison spring reference: game rule, FOVMOD 60/120 Hz ticks with warm-up, and the game clock passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
