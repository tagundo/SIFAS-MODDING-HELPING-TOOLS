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
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'mv-physics-')), 'manifest.json');
  fs.writeFileSync(file, JSON.stringify({ ...base, ...extra }));
  return capture.readManifest(file);
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

// renderFrame: warm-up frames at the start pose only when the preroll reaches the song start.
function fakePage() {
  const calls = [];
  globalThis.document = { querySelector: () => ({ toDataURL: () => 'data:image/png;base64,' }) };
  globalThis.mvFrameProbe = { scene: {
    time: -1, resize() {}, inspect() { return { time: this.time }; },
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
  globalThis.document = { querySelector: () => null };
  await assert.rejects(capture.applyAntiAliasing(direct, false), /no anti-aliasing control/);
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
  assert.equal(result.previewRestored, false);

  // A 4.87 Hz device grid trips the playback's slow-frame preview downscale: playback restarts
  // before the drawn frame so it is drawn at the pinned size.
  page = fakePage();
  globalThis.mvFrameProbe.scene.inspect = function () { return { time: this.time, previewScale: .75 }; };
  result = await capture.renderFrame(page, 49.649, 3, 4.87);
  const restart = page.calls.slice(-4, -1);
  assert.deepEqual(restart.map(([kind, value]) => [kind, kind === 'frame' ? Math.round(value * 1e3) / 1e3 : value]),
    [['playing', false], ['playing', true], ['frame', 49.649]]);
  assert.equal(result.previewRestored, true);

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
