/* MV Studio camera keys (mv-studio-camera-keys.js) on a stub editor context with the
   real undo history: no record → the original samples; one offset key moves every
   sample of the shot; linear/constant/bezier keys; the at-playhead edit creates or
   updates the key at round(local·60) (the snap-back fix); keys follow a moved shot;
   revert; the duration lock; a layer at order 30 sees the keyed pose; undo/redo
   rebakes identical arrays; Key current view (aspect correction and LiveCameraOffset);
   quaternion hemisphere continuity; split-screen sub camera shots; static and editor-made shots of non-native
   projects; simplify; async layers; and the no-regression rule: an unedited project is
   never written to and gets no project.editor. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-split.js');
require('../webtools/web/static/mv-studio-camera-math.js');
require('../webtools/web/static/mv-studio-edit-history.js');
require('../webtools/web/static/mv-studio-timeline-interact.js');
require('../webtools/web/static/mv-studio-camera-keys.js');
require('../webtools/web/static/mv-studio-scene.js');
const M = globalThis.MVStudioCameraMath, K = globalThis.MVStudioCameraKeys, H = globalThis.MVStudioEditHistory, S = globalThis.MVStudioScene;
const plugin = K.plugin;
const copy = (value) => JSON.parse(JSON.stringify(value));
const near = (actual, expected, tolerance, message) => assert(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} != ${expected}`);
const nearVector = (actual, expected, tolerance, message) => actual.forEach((value, index) => near(value, expected[index], tolerance, `${message}[${index}]`));
const angle = (a, b) => {
  const d = M.multiply(M.normalize(a), M.conjugate(M.normalize(b)));
  return 2 * Math.atan2(Math.hypot(d[0], d[1], d[2]), Math.abs(d[3])) * 180 / Math.PI;
};

assert(Array.isArray(globalThis.MVStudioPlugins) && globalThis.MVStudioPlugins.includes(plugin), 'registers as an editor plugin');
assert.equal(plugin.id, 'camera-keys');

// A dense 60 Hz shot: a slow dolly and pan, as the importer stores it.
function samples(count, { flip = false, phase = 0 } = {}) {
  return Array.from({ length: count }, (_, index) => {
    const s = index / (count - 1);
    let rotation = M.normalize(M.eulerZXYToQuaternion({ pan: 160 + 30 * s + phase, tilt: -3 + 2 * s, roll: .5 }));
    if (flip && index % 2) rotation = rotation.map((value) => -value);
    return { time: index / 60, position: [10 - 2 * s, 3.35 + .1 * Math.sin(s * 5), 30 - 4 * s], rotation, fov: 28 + 2 * s };
  });
}

function nativeProject() {
  const shot = (id, start, count, options) => ({ id, start, duration: (count - 1) / 60, label: `${Math.round(start * 60)}_${Math.round(start * 60) + count - 1}`,
    values: { clipIn: 0, timeScale: 1, preExtrapolationMode: 1, postExtrapolationMode: 1, preExtrapolationTime: 0, postExtrapolationTime: 1 / 60,
      playableClass: 'AnimationPlayableAsset', m_Position: { x: 0, y: 0, z: 0 }, keyframes: samples(count, options) },
    editableValues: ['clipIn', 'timeScale', 'preExtrapolationMode', 'postExtrapolationMode', 'preExtrapolationTime', 'postExtrapolationTime', 'keyframes'] });
  return {
    version: 1, name: 'Camera MV', duration: 12, nativeTimeline: true, source: { kind: 'game' },
    tracks: [
      { id: 'cam', kind: 'camera', label: 'CameraMotion/Camera1', nativeClass: 'AnimationTrack', binding: '/EntryPoint/Live/Cameras/MainCamera',
        events: [shot('cam:0', 0, 121), shot('cam:1', 121 / 60, 181, { phase: 40 }), shot('cam:2', 303 / 60, 61, { flip: true })] },
      { id: 'offset', kind: 'camera', label: 'CameraOffset', nativeClass: 'LiveCameraOffsetTrack', binding: '/EntryPoint/Live/Cameras/MainCamera',
        events: [{ id: 'offset:0', start: 0, duration: 4, values: { playableClass: 'LiveCameraOffsetClip', intensity: 1, memberPosition: 1 } }] },
      { id: 'light', kind: 'lighting', label: 'BaseLight', nativeClass: 'LiveBaseLightTrack', events: [{ id: 'light:0', start: 0, duration: 3, values: { color: 1 } }] },
    ],
  };
}

function harness(project, { scene = null, tab = 'camera' } = {}) {
  let time = 0, history;
  const log = { seeks: [], refreshed: [], reports: [] };
  const ctx = {
    project: () => project, time: () => time, duration: () => project.duration, playing: () => false, pause() {},
    seek(seconds) { time = seconds; log.seeks.push(seconds); }, selection: () => null, select() {},
    editor(create = false) {
      if (create && !project.editor) project.editor = { version: 1, originals: {} };
      return project.editor || null;
    },
    edited: (id) => history.editedEvents().has(id), extrapolationAuto: () => false, scene: () => scene,
    t: (label) => label, format: (label, values) => label.replace(/\{(\w+)\}/g, (match, key) => key in values ? String(values[key]) : match),
    renderTimeline() { history.invalidate(); }, refreshLane(id) { history.invalidate(); log.refreshed.push(id); },
    renderPanel() {}, renderEvent() {}, report(message, error) { log.reports.push([message, !!error]); }, locked: () => false,
    frameRate: 60, snap: (seconds) => Math.round(seconds * 60) / 60, activeTab: () => tab,
  };
  history = H.create({ getProject: () => project, limit: 200,
    onChange: ({ command, direction }) => plugin.projectChanged(ctx, { reason: 'history', command, direction }) });
  ctx.history = history;
  plugin.attach(ctx);
  plugin.projectChanged(ctx, { reason: 'load' });
  return { ctx, history, log, at(seconds) { time = seconds; } };
}

const event = (project, id) => project.tracks.flatMap((track) => track.events).find((item) => item.id === id);
const track = (project, id) => project.tracks.find((item) => item.id === id);
const original = (id) => nativeProject().tracks[0].events.find((item) => item.id === id).values.keyframes;

function unedited() {
  const project = nativeProject(), before = copy(project);
  const arrays = project.tracks[0].events.map((item) => item.values.keyframes);
  const { ctx, history } = harness(project);
  plugin.projectChanged(ctx, { reason: 'reload' });
  plugin.projectChanged(ctx, { reason: 'reimport' });
  // An unrelated history command (a light value) rebakes nothing.
  history.apply({ label: 'Edit value', changes: [{ target: { kind: 'event', track: 'light', event: 'light:0' }, path: ['values', 'color'], after: 2 }] });
  history.undo();
  K.requestBake(ctx, {});
  assert.deepEqual(project, { ...before, editor: project.editor }, 'tracks deep-equal');
  assert.deepEqual(Object.keys(project.editor.originals), ['light:0'], 'only the light edit made an original');
  project.tracks[0].events.forEach((item, index) => assert.equal(item.values.keyframes, arrays[index], 'camera samples never rewritten'));
  const fresh = nativeProject();
  const second = harness(fresh);
  K.requestBake(second.ctx, {});
  assert.equal(fresh.editor, undefined, 'attach/projectChanged/requestBake on an unedited project create no editor');
  for (const shot of fresh.tracks[0].events) assert.equal(K.differs(second.ctx, shot), false);
  assert.equal(plugin.clipConstraints, undefined, 'the camera editor locks no shot length');
  assert.equal(plugin.valueControl(second.ctx, { track: fresh.tracks[2], event: fresh.tracks[2].events[0], key: 'color', value: 1 }), undefined);
  assert.equal(plugin.valueControl(second.ctx, { track: fresh.tracks[0], event: fresh.tracks[0].events[0], key: 'm_Position', value: {} }), null,
    'raw playable transforms are hidden on camera shots');
  assert.equal(plugin.valueControl(second.ctx, { track: fresh.tracks[0], event: fresh.tracks[0].events[0], key: 'clipIn', value: 0 }), undefined);
}

function offsetKey() {
  const project = nativeProject();
  const { ctx, history, at } = harness(project);
  const shot = event(project, 'cam:0'), other = event(project, 'cam:1');
  const otherArray = other.values.keyframes;
  at(.5);
  assert(K.setChannels(ctx, 'offset', { z: 1 }), 'Dolly +1 at the playhead');
  const record = project.editor.camera.shots['cam:0'];
  assert.deepEqual(record.keys.map((key) => key.frame), [30], 'key at round(local·60)');
  assert.equal(record.mode, 'offset');
  assert.equal(record.space, 'view');
  const before = original('cam:0');
  assert.equal(shot.values.keyframes.length, before.length, 'same sample count');
  shot.values.keyframes.forEach((sample, index) => {
    assert.equal(sample.time, before[index].time, 'identical time floats');
    assert.deepEqual(Object.keys(sample), ['time', 'position', 'rotation', 'fov'], 'the exporter key set');
    const forward = M.rotateVector(M.normalize(before[index].rotation), [0, 0, -1]);
    nearVector(sample.position.map((value, axis) => value - before[index].position[axis]), forward, 1e-12, `dolly moves sample ${index} 1 m forward`);
    assert.deepEqual(sample.rotation, before[index].rotation, 'rotation untouched bit for bit');
    assert.equal(sample.fov, before[index].fov, 'fov untouched');
  });
  assert.equal(other.values.keyframes, otherArray, 'the other shot is not rewritten');
  assert.deepEqual(project.editor.originals['cam:0'].values.keyframes, before, 'originals captured before the first write');
  assert(ctx.edited('cam:0'));

  // The same frame again updates that key; another channel keeps the dolly.
  at(30.4 / 60);
  K.setChannels(ctx, 'offset', { pan: 5 });
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys.map((key) => [key.frame, key.values.z, key.values.pan]), [[30, 1, 5]]);
  assert.equal(history.size().undo, 2, 'one history entry per field edit');

  // Undo/redo rebake identical arrays.
  const keyed = copy(shot.values.keyframes);
  history.undo();
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys[0].values.pan, 0);
  history.undo();
  assert.deepEqual(shot.values.keyframes, before, 'undo back to the original samples');
  assert(!ctx.edited('cam:0'), 'not edited after undo');
  history.redo();
  history.redo();
  assert.deepEqual(shot.values.keyframes, keyed, 'redo rebakes the same samples');

  // Revert: one command removes the record and the samples are the originals again.
  assert.equal(plugin.revertEvent(ctx, track(project, 'cam'), shot), true);
  assert.equal(project.editor.camera.shots['cam:0'], undefined, 'record removed');
  assert.deepEqual(shot.values.keyframes, before);
  assert(!ctx.edited('cam:0'));
  assert.equal(history.peekUndo().label, 'Revert shot');
  history.undo();
  assert.deepEqual(shot.values.keyframes, keyed, 'undo of revert');
}

function interpolation() {
  const project = nativeProject();
  const { ctx, history, at } = harness(project);
  const shot = event(project, 'cam:1'), start = shot.start;
  const before = original('cam:1');
  at(start);
  K.setChannels(ctx, 'offset', { x: 0 });
  at(start + 100 / 60);
  K.setChannels(ctx, 'offset', { x: 2 });
  K.selectKey(ctx, 'cam:1', 0);
  K.setKeyProperty(ctx, 'interp', 'linear');
  const record = project.editor.camera.shots['cam:1'];
  assert.deepEqual(record.keys.map((key) => [key.frame, key.interp]), [[0, 'linear'], [100, 'bezier']]);
  const delta = (index) => {
    const right = M.rotateVector(M.normalize(before[index].rotation), [-1, 0, 0]);
    const moved = shot.values.keyframes[index].position.map((value, axis) => value - before[index].position[axis]);
    return moved[0] * right[0] + moved[1] * right[1] + moved[2] * right[2];
  };
  near(delta(50), 1, 1e-9, 'two linear keys: half the delta halfway');
  near(delta(25), .5, 1e-9, 'a quarter');
  near(delta(150), 2, 1e-9, 'held after the last key');
  // Bezier (auto-clamped ends are flat): an ease, still the midpoint by symmetry.
  K.setKeyProperty(ctx, 'interp', 'bezier');
  near(delta(50), 1, 1e-9, 'bezier midpoint');
  assert(delta(10) < .1, 'eased start');
  // Free handles: converting keeps the curve; dragging one handle (the curve view) changes
  // only that channel's segment.
  const curveAt = (frame) => M.curve(K.normalizeRecord(project.editor.camera.shots['cam:1'], 181).keys, 'x', frame);
  const beforeFree = [20, 50, 80].map(curveAt);
  K.selectKey(ctx, 'cam:1', 0);
  K.setKeyProperty(ctx, 'handle', 'free');
  assert.equal(project.editor.camera.shots['cam:1'].keys[0].handle, 'free');
  [20, 50, 80].forEach((frame, index) => near(curveAt(frame), beforeFree[index], 1e-12, `free keeps the curve at ${frame}`));
  const yBefore = copy(shot.values.keyframes.map((sample) => sample.position));
  assert(K.setHandle(ctx, 'cam:1', 0, 'x', 'out', [30, 1.5]));
  const stored = project.editor.camera.shots['cam:1'].keys[0].handles.x.out;
  assert.deepEqual(stored, [30, 1.5], 'the dragged handle is stored');
  assert(curveAt(20) > beforeFree[0] + .1, 'the steeper handle lifts the start of the segment');
  assert.equal(history.peekUndo().label, 'Edit camera handle');
  history.undo();
  assert.deepEqual(shot.values.keyframes.map((sample) => sample.position), yBefore, 'undo restores the samples');
  K.setKeyProperty(ctx, 'handle', 'auto-clamped');
  assert.equal(project.editor.camera.shots['cam:1'].keys[0].handles, undefined, 'non-free keys store no handles');
  // Ease presets on the outgoing segment.
  K.ease(ctx, 'ease-out');
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys.map((key) => key.handle), ['auto-clamped', 'flat']);
  K.ease(ctx, 'ease-in');
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys.map((key) => key.handle), ['flat', 'auto-clamped']);
  K.ease(ctx, 'linear');
  assert.equal(project.editor.camera.shots['cam:1'].keys[0].interp, 'linear');
  // Moving a key stays between its neighbours.
  assert(K.moveKey(ctx, 'cam:1', 100, 400));
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys.map((key) => key.frame), [0, 180], 'clamped to the last frame');
  assert(K.moveKey(ctx, 'cam:1', 180, -5));
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys.map((key) => key.frame), [0, 1], 'clamped after the previous key');
  // Previous/next key move the playhead.
  at(start + 90 / 60);
  assert(K.stepKey(ctx, -1));
  near(ctx.time(), start + 1 / 60, 1e-12, 'previous key');
  assert(K.stepKey(ctx, -1));
  near(ctx.time(), start, 1e-12, 'first key');
  assert(!K.stepKey(ctx, -1), 'no key before the first');
  // Delete every key: the shot plays its original samples again.
  K.selectKey(ctx, 'cam:1', 0);
  assert(K.deleteKey(ctx));
  K.selectKey(ctx, 'cam:1', 1);
  assert(K.deleteKey(ctx));
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys, []);
  assert.deepEqual(shot.values.keyframes, before, 'no keys: original samples');
  assert(!ctx.edited('cam:1'));
  assert(history.size().undo > 5);
}

function keysMode() {
  const project = nativeProject();
  const { ctx, at } = harness(project);
  const shot = event(project, 'cam:0'), before = original('cam:0');
  at(.25);
  assert(K.setMode(ctx, 'keys', { confirm: false }));
  const record = project.editor.camera.shots['cam:0'];
  assert.equal(record.mode, 'keys');
  assert.deepEqual(record.keys.map((key) => key.frame), [0, 120], 'keys at the first and last frame');
  for (const index of [0, 120]) {
    nearVector(shot.values.keyframes[index].position, before[index].position, 1e-9, `key ${index} position`);
    assert(angle(shot.values.keyframes[index].rotation, before[index].rotation) < 1e-7, `key ${index} rotation`);
    near(shot.values.keyframes[index].fov, before[index].fov, 1e-12, 'key fov');
  }
  // Constant holds the first key until the last frame.
  K.selectKey(ctx, 'cam:0', 0);
  K.setKeyProperty(ctx, 'interp', 'constant');
  assert.deepEqual(shot.values.keyframes[119].position, shot.values.keyframes[0].position, 'constant holds');
  assert.notDeepEqual(shot.values.keyframes[120].position, shot.values.keyframes[0].position);
  // Absolute edit in keys mode at a new frame inserts a key with the current curve values.
  at(60 / 60);
  K.setChannels(ctx, 'absolute', { y: 5 });
  const keyed = project.editor.camera.shots['cam:0'].keys.find((key) => key.frame === 60);
  assert.equal(keyed.values.y, 5);
  near(keyed.values.x, project.editor.camera.shots['cam:0'].keys[0].values.x, 1e-12, 'other channels hold the curve value (constant)');
  near(shot.values.keyframes[60].position[1], 5, 1e-12);
  // Keys → offset keeps the pose at the key frames.
  const keyedPose = copy(shot.values.keyframes);
  assert(K.setMode(ctx, 'offset', { confirm: false }));
  assert.equal(project.editor.camera.shots['cam:0'].mode, 'offset');
  for (const frame of [0, 60, 120]) {
    nearVector(shot.values.keyframes[frame].position, keyedPose[frame].position, 1e-9, `offset pose at ${frame}`);
    assert(angle(shot.values.keyframes[frame].rotation, keyedPose[frame].rotation) < 1e-6);
  }
  // View ↔ world keeps the baked samples at the keys.
  const viewBaked = copy(shot.values.keyframes);
  assert(K.setSpace(ctx, 'world'));
  assert.equal(project.editor.camera.shots['cam:0'].space, 'world');
  for (const frame of [0, 60, 120]) nearVector(shot.values.keyframes[frame].position, viewBaked[frame].position, 1e-9, `world space at ${frame}`);
  K.setSpace(ctx, 'view');
  // Original motion again.
  assert(K.setMode(ctx, 'original', { confirm: false }));
  assert.deepEqual(shot.values.keyframes, before);
}

function followsMove() {
  const project = nativeProject();
  const { ctx, history, at } = harness(project);
  const shot = event(project, 'cam:1');
  at(shot.start + 30 / 60);
  K.setChannels(ctx, 'offset', { y: .5 });
  const baked = shot.values.keyframes;
  history.apply({ label: 'Move clip', changes: [{ target: { kind: 'event', track: 'cam', event: 'cam:1' }, path: ['start'], after: shot.start + .25 }] });
  assert.equal(shot.values.keyframes, baked, 'local keys: a move changes no sample');
  at(shot.start + 30 / 60);
  assert.equal(K.playheadShot(ctx).frame, 30, 'the key moved with the shot');
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys.map((key) => key.frame), [30]);
  return resizedShot(project, ctx, history, at, shot, baked);
}

// A resized shot with camera edits bakes on the 60 Hz grid of its new length: the original samples
// up to the shorter length (the same values bit for bit), the last pose held past the old end, and
// the keys on their frames. A length off the grid previews, but export refuses it.
async function resizedShot(project, ctx, history, at, shot, baked) {
  const count = baked.length, length = shot.duration;
  const resize = (duration) => history.apply({ label: 'Resize clip',
    changes: [{ target: { kind: 'event', track: 'cam', event: 'cam:1' }, path: ['duration'], after: duration }] });
  const grid = (frames, duration) => frames.forEach((sample, index) => assert.equal(sample.time, Math.min(index / 60, duration), `grid time ${index}`));
  // The next shot moves out of the way, so the playhead past the old end is in this shot.
  const next = event(project, 'cam:2');
  assert(history.apply({ label: 'Move clip', changes: [{ target: { kind: 'event', track: 'cam', event: 'cam:2' }, path: ['start'], after: next.start + 2 }] }));
  assert(resize(length + 30 / 60));
  let info = K.findShot(ctx, 'cam:1');
  assert.equal(info.editable, true, 'an edited shot stays editable at another length');
  assert.equal(info.count, count + 30);
  assert.equal(info.partialFrame, false);
  const longer = shot.values.keyframes;
  assert.equal(longer.length, count + 30, 'baked on the longer grid');
  grid(longer, shot.duration);
  assert.deepEqual(longer.slice(0, count), baked, 'the original grid keeps its baked samples');
  for (const sample of longer.slice(count)) assert.deepEqual({ ...sample, time: baked[count - 1].time }, baked[count - 1], 'the last pose holds');
  // A key past the old end.
  at(shot.start + (count + 10) / 60);
  assert(K.setChannels(ctx, 'offset', { x: .25 }));
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys.map((key) => key.frame), [30, count + 10]);
  assert.notDeepEqual(shot.values.keyframes[count + 20].position, longer[count + 20].position, 'the new key moves the held frames');
  await plugin.beforeExport(ctx);
  // Undo the key and the resize: back on the original grid with the original bake.
  history.undo();
  history.undo();
  assert.equal(shot.duration, length);
  assert.deepEqual(shot.values.keyframes, baked);
  // A shorter shot: the first samples of the original grid.
  assert(resize(length - 20 / 60));
  const shorter = shot.values.keyframes;
  assert.equal(shorter.length, count - 20);
  grid(shorter, shot.duration);
  shorter.forEach((sample, index) => assert.deepEqual({ ...sample, time: baked[index].time }, baked[index], `sample ${index}`));
  await plugin.beforeExport(ctx);
  // Off the grid: previewed, refused at export.
  assert(resize(length + .005));
  info = K.findShot(ctx, 'cam:1');
  assert.equal(info.editable, true);
  assert.equal(info.partialFrame, true);
  assert.equal(shot.values.keyframes.length, Math.ceil((length + .005) * 60 - 1e-6) + 1);
  await assert.rejects(plugin.beforeExport(ctx), { message: 'Set the length of camera shots with camera edits to whole frames (1/60 s) before exporting.' });
  // A resized shot without camera edits exports its timing only and is never refused.
  history.undo();
  history.undo();
  assert(K.revertShot(ctx, track(project, 'cam'), shot));
  assert.deepEqual(shot.values.keyframes, original('cam:1'));
  assert(resize(length + .005));
  assert.equal(K.differs(ctx, shot), false, 'no edit: the original samples stay');
  await plugin.beforeExport(ctx);
}

function layers() {
  const project = nativeProject();
  const { ctx, history, at } = harness(project);
  const shot = event(project, 'cam:0'), before = original('cam:0');
  let seen = null;
  const remove = K.registerLayer({ id: 'probe', order: 30, affects: (context, item) => item.event.id === 'cam:0',
    apply(context, item, frames) {
      seen = { first: frames[0].position.slice(), t: frames[10].t, count: frames.length };
      // In-place writes are allowed: a layer gets copies of the samples.
      for (const frame of frames) frame.position[1] += .5;
    } });
  try {
    K.requestBake(ctx, { reason: 'test' });
    assert(seen, 'the layer applies to the shot without keys');
    nearVector(seen.first, before[0].position, 0, 'it sees the original pose');
    near(shot.values.keyframes[0].position[1], before[0].position[1] + .5, 1e-12, 'its output is baked');
    assert(ctx.edited('cam:0'));
    at(0);
    K.setChannels(ctx, 'offset', { z: 2 });
    const forward = M.rotateVector(M.normalize(before[0].rotation), [0, 0, -2]);
    nearVector(seen.first, before[0].position.map((value, axis) => value + forward[axis]), 1e-12, 'order 30 sees the keyed pose');
    near(seen.t, shot.start + before[10].time, 0, 'absolute sample times');
    assert.equal(seen.count, before.length);
  } finally { remove(); }
  assert.deepEqual(project.editor.originals['cam:0'].values.keyframes, before, 'the layer never wrote into the originals');
  // Without the layer the keys alone remain after the next bake.
  K.requestBake(ctx, {});
  near(shot.values.keyframes[0].position[1], before[0].position[1] + M.rotateVector(M.normalize(before[0].rotation), [0, 0, -2])[1], 1e-12, 'layer gone');
  history.undo();
  assert.deepEqual(shot.values.keyframes, before, 'nothing left: originals');
}

async function asyncLayers() {
  const project = nativeProject();
  const { ctx } = harness(project);
  const signals = [];
  let release;
  const remove = K.registerLayer({ id: 'slow', order: 30, affects: (context, item) => item.event.id === 'cam:1',
    prepare(context, shots, signal) { signals.push(signal); return new Promise((resolve) => { release = resolve; }); },
    apply(context, item, frames) { for (const frame of frames) frame.fov = 50; } });
  try {
    const first = K.requestBake(ctx, { events: ['cam:1'], reason: 'test' });
    const releaseFirst = release;
    const second = K.requestBake(ctx, { events: ['cam:1'], reason: 'test' });
    assert.equal(signals[0].aborted, true, 'a newer request cancels the older one');
    releaseFirst();
    await first;
    assert.notEqual(event(project, 'cam:1').values.keyframes[0].fov, 50, 'the cancelled bake wrote nothing');
    release();
    await second;
    assert.equal(event(project, 'cam:1').values.keyframes[0].fov, 50, 'the newest bake lands');
    await plugin.beforeSave(ctx);
  } finally { remove(); }
}

function keyView() {
  const project = nativeProject();
  const view = { mode: 'orbit', position: [-3, 2.5, 9], quaternion: M.normalize([.05, .2, -.01, .97]), fov: 40, aspect: 4 / 3 };
  const scene = { getViewPose: () => ({ ...view }), cameraOffsetAt: (time, binding) => binding === '/EntryPoint/Live/Cameras/MainCamera' ? .3 : 0,
    onViewChange: () => () => {}, setGameCameraHelper() {} };
  const { ctx, log, at } = harness(project, { scene });
  const shot = event(project, 'cam:1');
  at(shot.start + 1.004);
  assert(K.keyView(ctx));
  const frame = 60;
  assert.deepEqual(project.editor.camera.shots['cam:1'].keys.map((key) => key.frame), [frame]);
  near(ctx.time(), shot.start + frame / 60, 1e-12, 'the playhead lands on the keyed frame');
  const pose = M.sampleFrames(shot.values.keyframes, frame / 60);
  const rotation = M.threeToUnityQuaternion(view.quaternion);
  const offset = M.rotateVector(rotation, [0, .3, 0]);
  nearVector(pose.position, M.threeToUnityPosition(view.position).map((value, axis) => value - offset[axis]), 1e-9, 'LiveCameraOffset removed along the rig up');
  assert(angle(pose.rotation, rotation) < 1e-6, 'rotation = the view');
  near(pose.fov, 40 * M.aspectCorrection(4 / 3), 1e-9, 'authored FOV = view FOV × aspect correction');
  near(M.aspectCorrection(4 / 3), .75, 1e-12);
  // In keys mode the same view gives the same pose.
  K.setMode(ctx, 'keys', { confirm: false });
  view.position = [-2, 2, 7];
  assert(K.keyView(ctx));
  const again = M.sampleFrames(shot.values.keyframes, frame / 60);
  nearVector(again.position, M.threeToUnityPosition(view.position).map((value, axis) => value - offset[axis]), 1e-9, 'keys mode');
  // Game camera mode: not keyed.
  view.mode = 'live';
  assert.equal(K.keyView(ctx), false);
  assert.equal(log.reports.at(-1)[0], 'Switch the preview camera to Free camera to key the view.');
  // A binding-less (non-native lens) track: no aspect correction, no offset.
  const plain = nativeProject();
  plain.tracks[0].nativeClass = undefined;
  plain.tracks[0].binding = undefined;
  const second = harness(plain, { scene: { ...scene, getViewPose: () => ({ ...view, mode: 'orbit' }) } });
  second.at(.5);
  assert(K.keyView(second.ctx));
  near(M.sampleFrames(event(plain, 'cam:0').values.keyframes, .5).fov, 40, 1e-9, 'no correction without the native lens');
}

// Split-screen sub cameras (12056): their shots take keys, curves and undo like the main camera's,
// relative to their own rig; the follow camera and other layers stay on the main camera.
const SPLIT = '/EntryPoint/Live/Cameras/SplitScreenEffect/Cameras';
function splitProject() {
  const project = nativeProject();
  const shot = (id, start, count, phase) => ({ ...copy(project.tracks[0].events[0]), id, start, duration: (count - 1) / 60, label: id,
    values: { ...copy(project.tracks[0].events[0].values), keyframes: samples(count, { phase }) } });
  project.tracks.push(
    { id: 'sub1', kind: 'camera', label: 'Split/SubCamera1', nativeClass: 'AnimationTrack', binding: `${SPLIT}/SubCamera1`,
      events: [shot('sub1:0', 1, 61, 90), shot('sub1:1', 6, 31, 100)] },
    { id: 'sub1-offset', kind: 'camera', label: 'Split/SubCamera1 offset', nativeClass: 'LiveCameraOffsetTrack', binding: `${SPLIT}/SubCamera1`,
      events: [{ id: 'sub1-offset:0', start: 1, duration: 1, values: { playableClass: 'LiveCameraOffsetClip', intensity: 1, memberPosition: 1 } }] },
    { id: 'sub3', kind: 'camera', label: 'Split/SubCamera3', nativeClass: 'AnimationTrack', binding: `${SPLIT}/SubCamera3`,
      events: [shot('sub3:0', 1, 61, 120)] });
  return project;
}

function subCameras() {
  const project = splitProject(), before = copy(project);
  const view = { mode: 'orbit', position: [-3, 2.5, 9], quaternion: M.normalize([.05, .2, -.01, .97]), fov: 40, aspect: 4 / 3 };
  const bindings = [];
  const scene = { getViewPose: () => ({ ...view }), onViewChange: () => () => {}, setGameCameraHelper() {},
    cameraOffsetAt: (time, binding) => { bindings.push(binding); return binding === `${SPLIT}/SubCamera1` ? .2 : 0; } };
  const { ctx, history, at } = harness(project, { scene });
  const seen = [];
  const remove = K.registerLayer({ id: 'probe-main', order: 30, affects: () => true, apply(context, item) { seen.push(item.event.id); } });
  try {
    K.requestBake(ctx, {});
    assert.deepEqual([...new Set(seen)].sort(), ['cam:0', 'cam:1', 'cam:2'], 'layers bake the main camera only');
  } finally { remove(); }
  K.requestBake(ctx, {});
  assert.deepEqual(project.tracks.slice(3), before.tracks.slice(3), 'sub camera shots untouched');
  assert(Object.keys(project.editor?.originals || {}).every((id) => id.startsWith('cam:')), 'the layer wrote main camera shots only');
  assert.deepEqual(K.mainCameraShots(ctx).map((item) => item.event.id), ['cam:0', 'cam:1', 'cam:2']);
  assert.deepEqual(K.cameraShots(ctx).map((item) => item.event.id).sort(), ['cam:0', 'cam:1', 'cam:2', 'sub1:0', 'sub1:1', 'sub3:0']);
  assert.equal(K.camera(ctx), 'main');
  at(1.5);
  assert.equal(K.editedShot(ctx).event.id, 'cam:0', 'the main camera by default');
  assert.equal(K.setCamera(ctx, `${SPLIT}/SubCamera2`), false, 'a sub camera the MV does not have');
  assert(K.setCamera(ctx, `${SPLIT}/SubCamera1`));
  let shot = K.editedShot(ctx);
  assert.equal(shot.event.id, 'sub1:0');
  assert.deepEqual([shot.sub, shot.index, shot.total, shot.lens, shot.count, shot.frame], [1, 0, 2, false, 61, 30]);
  // playheadShot stays the main camera's (the follow camera covers it), whichever camera is edited.
  assert.equal(K.playheadShot(ctx).event.id, 'cam:0', 'playheadShot: the main camera');
  assert.equal(K.playheadShot(ctx, 1.5, `${SPLIT}/SubCamera1`).event.id, 'sub1:0', 'or the camera asked for');
  at(4);
  assert.equal(K.editedShot(ctx), null, 'no sub camera shot here (no hold past a sub shot)');
  assert.equal(K.playheadShot(ctx).event.id, 'cam:1');
  at(6.75);
  assert.equal(K.editedShot(ctx), null, 'nor past the last sub shot (6..6.5)');
  assert.equal(K.playheadShot(ctx).event.id, 'cam:2', 'the main camera holds its last shot');
  // An offset key moves the sub camera along its own view; the main camera is not rewritten.
  const sub = event(project, 'sub1:0'), main = event(project, 'cam:0'), mainSamples = main.values.keyframes;
  const original = copy(sub.values.keyframes);
  at(1.5);
  assert(K.setChannels(ctx, 'offset', { z: 1 }));
  assert.deepEqual(project.editor.camera.shots['sub1:0'].keys.map((key) => key.frame), [30]);
  sub.values.keyframes.forEach((sample, index) => {
    const forward = M.rotateVector(M.normalize(original[index].rotation), [0, 0, -1]);
    nearVector(sample.position.map((value, axis) => value - original[index].position[axis]), forward, 1e-12, `sub sample ${index}`);
  });
  assert.equal(main.values.keyframes, mainSamples, 'the main camera is not rewritten');
  assert(ctx.edited('sub1:0'));
  // Undo and redo rebake the sub camera shot.
  history.undo();
  assert.deepEqual(sub.values.keyframes, original);
  history.redo();
  near(sub.values.keyframes[0].position[2] - original[0].position[2], M.rotateVector(M.normalize(original[0].rotation), [0, 0, -1])[2], 1e-12, 'redo');
  // Key current view: the sub camera's own LiveCameraOffset is removed and its FOV is the view's (no lens correction).
  at(1 + 45 / 60);
  assert(K.keyView(ctx));
  assert.equal(bindings.at(-1), `${SPLIT}/SubCamera1`);
  const pose = M.sampleFrames(sub.values.keyframes, 45 / 60), rotation = M.threeToUnityQuaternion(view.quaternion);
  const up = M.rotateVector(rotation, [0, .2, 0]);
  nearVector(pose.position, M.threeToUnityPosition(view.position).map((value, axis) => value - up[axis]), 1e-9, 'the view, offset removed');
  assert(angle(pose.rotation, rotation) < 1e-6);
  near(pose.fov, 40, 1e-9, 'a sub camera has no aspect correction');
  // A key in another sub camera's shot: one record per shot.
  assert(K.setCamera(ctx, `${SPLIT}/SubCamera3`));
  assert.equal(K.editedShot(ctx).event.id, 'sub3:0');
  assert(K.setChannels(ctx, 'offset', { fov: 2 }));
  assert.deepEqual(Object.keys(project.editor.camera.shots).sort(), ['sub1:0', 'sub3:0']);
  // A timeline selection picks its camera.
  plugin.selectionChanged(ctx, { track: track(project, 'cam'), event: main });
  assert.equal(K.camera(ctx), 'main');
  plugin.selectionChanged(ctx, { track: track(project, 'sub1'), event: sub });
  assert.equal(K.camera(ctx), `${SPLIT}/SubCamera1`);
  plugin.selectionChanged(ctx, { track: track(project, 'sub1-offset'), event: event(project, 'sub1-offset:0') });
  assert.equal(K.camera(ctx), `${SPLIT}/SubCamera1`, 'an offset clip is not a camera shot');
  // Moving and resizing a sub camera shot keeps its keys on their frames.
  assert(history.apply({ label: 'Resize clip', changes: [{ target: { kind: 'event', track: 'sub1', event: 'sub1:0' }, path: ['duration'], after: 1.5 }] }));
  assert.equal(sub.values.keyframes.length, 91, 'the longer grid');
  assert.deepEqual(project.editor.camera.shots['sub1:0'].keys.map((key) => key.frame), [30, 45]);
  // Revert shot restores the timing and the original samples.
  assert(K.revertShot(ctx, track(project, 'sub1'), sub));
  assert.equal(sub.duration, 1);
  assert.deepEqual(sub.values.keyframes, original);
  // Reopening a project goes back to the main camera.
  plugin.projectChanged(ctx, { reason: 'load' });
  assert.equal(K.camera(ctx), 'main');
}

// "Add follow camera" (mv-studio-camera-follow.js) covers the main camera's shot at the playhead,
// whichever camera the editor works on. The follow module registers its layer when it loads, so it
// runs in its own context here (this file's other layer checks see only their own layers).
async function followCoversMainShot() {
  const context = vm.createContext({ console, setTimeout, clearTimeout, AbortController, DOMException, Promise });
  context.window = context;
  for (const file of ['mv-studio-split.js', 'mv-studio-camera-math.js', 'mv-studio-edit-history.js', 'mv-studio-timeline-interact.js',
    'mv-studio-timeline-tabs.js', 'mv-studio-camera-keys.js', 'mv-studio-camera-follow.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static', file), 'utf8'), context, { filename: file });
  }
  const keys = context.MVStudioCameraKeys, follow = context.MVStudioCameraFollow;
  const project = splitProject();
  project.performers = [{ id: 'p1', position: 1, glb: '/x.glb', transform: { position: [0, 0, 0] } }];
  const scene = { memberTargets: () => [{ slot: 1, id: 'p1', parts: [0], facing: true }], onViewChange: () => () => {}, setGameCameraHelper() {},
    async sampleMemberPath({ times }) { return { positions: new Float64Array(3 * times.length), yaw: new Float64Array(times.length) }; } };
  let time = 0, history;
  const ctx = { project: () => project, time: () => time, duration: () => project.duration, playing: () => false, pause() {},
    seek(seconds) { time = seconds; }, selection: () => null, select() {},
    editor(create = false) { if (create && !project.editor) project.editor = { version: 1, originals: {} }; return project.editor || null; },
    edited: (id) => history.editedEvents().has(id), extrapolationAuto: () => false, scene: () => scene, t: (label) => label,
    format: (label, values) => label.replace(/\{(\w+)\}/g, (match, key) => key in values ? String(values[key]) : match), make() { throw new Error('no DOM'); },
    renderTimeline() { history.invalidate(); }, refreshLane() { history.invalidate(); }, renderPanel() {}, renderEvent() {}, report() {},
    locked: () => false, frameRate: 60, snap: (seconds) => Math.round(seconds * 60) / 60, activeTab: () => 'camera', snapTargets: () => [time] };
  history = context.MVStudioEditHistory.create({ getProject: () => project, limit: 200, onChange: ({ command, direction }) => {
    keys.plugin.projectChanged(ctx, { reason: 'history', command, direction });
    follow.plugin.projectChanged(ctx, { reason: 'history', command, direction });
  } });
  ctx.history = history;
  keys.plugin.attach(ctx); follow.plugin.attach(ctx);
  keys.plugin.projectChanged(ctx, { reason: 'load' }); follow.plugin.projectChanged(ctx, { reason: 'load' });
  const span = (rig) => [Math.round(rig.start * 60), Math.round(rig.end * 60)];
  const cam1 = [121, 301];   // cam:1 (2.0167..5.0167 s); sub1:0 is 1..2 s, sub1:1 6..6.5 s, sub3:0 1..2 s
  time = 2.6;
  assert.deepEqual(span(follow.addRig(ctx, { blendIn: 0, blendOut: 0 })), cam1, 'main camera edited: the main shot');
  history.undo();
  // The camera editor switches to a sub camera (a sub clip selected on the timeline).
  keys.plugin.selectionChanged(ctx, { track: track(project, 'sub1'), event: event(project, 'sub1:0') });
  assert.equal(keys.camera(ctx), `${SPLIT}/SubCamera1`);
  time = 1.5;
  assert.equal(keys.editedShot(ctx).event.id, 'sub1:0');
  time = 2.6;
  assert.deepEqual(span(follow.addRig(ctx, { blendIn: 0, blendOut: 0 })), cam1, 'sub camera edited: still the main shot');
  history.undo();
  // Past the main camera's last shot (cam:2 ends at 6.05 s, a game source holds it) and in no sub shot.
  time = 8;
  assert.deepEqual(span(follow.addRig(ctx, { blendIn: 0, blendOut: 0 })), [303, 363], 'the held main shot, not a 4 s rig at the playhead');
  assert.equal(keys.camera(ctx), `${SPLIT}/SubCamera1`, 'adding a rig leaves the edited camera alone');
  await keys.pending(ctx);
}

// Camera shot extrapolation (the preview and the editor): Unity's TimelineClip.GetExtrapolatedTime
// for None 0, Hold 1, Loop 2, PingPong 3 and Continue 4, inside the stored pre/post window.
function extrapolation() {
  const shot = (pre, post, preTime = 1, postTime = 3) => ({ id: 'e', start: 2, duration: 1.5,
    values: { preExtrapolationMode: pre, postExtrapolationMode: post, preExtrapolationTime: preTime, postExtrapolationTime: postTime } });
  // Unity: Loop time % d (before: d - (-t % d)); PingPong d - |t mod 2d - d|; Hold and Continue the end pose here.
  const cases = [
    [1, 1, [[2.5, .5], [1.5, 0], [4.25, 1.5], [6.5, 1.5]]],
    [2, 2, [[4.25, .75], [5, 0], [5.75, .75], [3.5, 1.5], [1.25, .75], [1, .5], [.5, 1.5]]],
    [3, 3, [[4.25, .75], [5, 0], [5.75, .75], [6.5, 1.5], [1.25, .75], [1, 1], [-1, 0]]],
    [4, 4, [[4.25, 1.5], [1.25, 0]]],
    [0, 0, [[4.25, 1.5], [1.25, 0], [2.75, .75]]],
  ];
  for (const [pre, post, times] of cases) {
    for (const [time, local] of times) {
      near(S.cameraLocalTime(shot(pre, post), time), local, 1e-12, `mode ${pre}/${post} at ${time}`);
    }
  }
  // Inside the shot the time itself; Hold and None exactly the clamp the preview always used.
  for (let index = 0; index <= 400; index++) {
    const time = -1 + index * .02, event = shot(1, 1);
    assert.equal(S.cameraLocalTime(event, time), Math.min(event.duration, Math.max(0, time - event.start)), `clamp at ${time}`);
    assert.equal(S.cameraLocalTime(shot(0, 0), time), Math.min(1.5, Math.max(0, time - 2)));
  }
  // Which shot plays in a gap: the windows of every extrapolating mode, none for None.
  const track = (pre, post) => ({ events: [shot(pre, post), { id: 'next', start: 7, duration: 1, values: {} }] });
  for (const mode of [1, 2, 3, 4]) {
    assert.equal(S.activeCameraEvent(track(mode, mode), 4.25)?.id, 'e', `post window, mode ${mode}`);
    assert.equal(S.activeCameraEvent(track(mode, mode), 1.25)?.id, 'e', `pre window, mode ${mode}`);
    assert.equal(S.activeCameraEvent(track(mode, mode), 6.75), null, 'past the post window');
    assert.equal(S.activeCameraEvent(track(mode, mode), .75), null, 'before the pre window');
  }
  assert.equal(S.activeCameraEvent(track(0, 0), 4.25), null, 'None: no shot in the gap');
  assert.equal(S.activeCameraEvent(track(5, 5), 4.25), null, 'an unknown mode is no shot');
  // The camera editor follows the same shot and frame at the playhead.
  const project = nativeProject();
  const first = project.tracks[0].events[0];
  project.tracks[0].events = [first, { ...project.tracks[0].events[1], start: 4 }];
  Object.assign(first.values, { postExtrapolationMode: 2, postExtrapolationTime: 2 });
  const { ctx, at } = harness(project);
  for (const [mode, time, frame] of [[2, 2.5, 30], [2, 3.75, 105], [3, 2.5, 90], [3, 3.75, 15], [4, 3.5, 120], [1, 3.5, 120]]) {
    first.values.postExtrapolationMode = mode;
    at(time);
    const playing = K.playheadShot(ctx);
    assert.equal(playing && playing.event.id, 'cam:0', `mode ${mode} at ${time}`);
    assert.equal(playing.frame, frame, `mode ${mode} at ${time}: frame`);
    assert.equal(S.activeCameraEvent(project.tracks[0], time), first);
    near(S.cameraLocalTime(first, time) * 60, frame, 1e-9, 'the scene shows that frame');
  }
  first.values.postExtrapolationMode = 0;
  at(2.5);
  assert.equal(K.playheadShot(ctx), null, 'None: no shot in the gap');
}

function hemisphere() {
  const project = nativeProject();
  const { ctx, at } = harness(project);
  const shot = event(project, 'cam:2'), before = original('cam:2');
  assert(before.some((sample, index) => index && M.dot(sample.rotation, before[index - 1].rotation) < 0), 'the source flips hemispheres');
  at(shot.start + .1);
  K.setChannels(ctx, 'offset', { pan: 10 });
  shot.values.keyframes.forEach((sample, index) => {
    if (index) assert(M.dot(sample.rotation, shot.values.keyframes[index - 1].rotation) >= 0, `continuous at ${index}`);
    near(Math.hypot(...sample.rotation), 1, 1e-12, 'normalized');
    const expected = M.multiply(M.normalize(before[index].rotation), M.eulerZXYToQuaternion({ pan: 10 }));
    assert(angle(sample.rotation, expected) < 1e-7, 'pan +10 in the rig frame');
  });
}

function absoluteEdit() {
  const project = nativeProject();
  const { ctx, at } = harness(project);
  const shot = event(project, 'cam:0'), before = original('cam:0');
  at(40 / 60);
  // The Result row: typing an absolute FOV and pan keys the deltas that reach them.
  K.setChannels(ctx, 'absolute', { fov: 35 });
  near(shot.values.keyframes[40].fov, 35, 1e-12, 'absolute FOV at the key');
  near(shot.values.keyframes[0].fov - before[0].fov, 35 - before[40].fov, 1e-12, 'one key: the same delta over the shot');
  const euler = M.quaternionToEulerZXY(before[40].rotation);
  K.setChannels(ctx, 'absolute', { pan: euler.pan + 12 });
  const found = M.quaternionToEulerZXY(shot.values.keyframes[40].rotation, euler);
  near(found.pan, euler.pan + 12, 1e-9, 'absolute pan');
  near(found.tilt, euler.tilt, 1e-9, 'tilt kept');
  near(found.roll, euler.roll, 1e-9, 'roll kept');
  K.setChannels(ctx, 'absolute', { y: 4 });
  near(shot.values.keyframes[40].position[1], 4, 1e-12, 'absolute Y in view space');
  nearVector([shot.values.keyframes[40].position[0], shot.values.keyframes[40].position[2]], [before[40].position[0], before[40].position[2]], 1e-12, 'X/Z kept');
}

function simplifyShot() {
  const project = nativeProject();
  const { ctx, at } = harness(project);
  const shot = event(project, 'cam:1'), before = original('cam:1');
  at(shot.start + 1);
  assert(K.convertToKeys(ctx));
  const record = project.editor.camera.shots['cam:1'];
  assert.equal(record.mode, 'keys');
  assert(record.keys.length < before.length / 3, `sparse keys (${record.keys.length})`);
  assert(record.keys.every((key) => key.interp === 'linear'));
  shot.values.keyframes.forEach((sample, index) => {
    nearVector(sample.position, before[index].position, .002 + 1e-9, `within 2 mm at ${index}`);
    assert(angle(sample.rotation, before[index].rotation) < .1, `within tolerance at ${index}`);
    near(sample.fov, before[index].fov, .01 + 1e-9, 'fov');
  });
}

function nonNative() {
  const project = { version: 1, name: 'Mod MV', duration: 20, nativeTimeline: false, tracks: [
    { id: 'camera', kind: 'camera', binding: 'MainCamera', label: 'Camera', events: [
      { id: 'static', start: 2, duration: 2, values: { position: [0, 1.5, 5], rotation: [0, 0, 0, 1], fov: 35 }, editableValues: ['fov', 'position', 'rotation'] },
      { id: 'fov-only', start: 5, duration: 2, values: { fov: 40 }, editableValues: ['fov'] }] }] };
  const before = copy(project);
  const scene = { getViewPose: () => ({ mode: 'orbit', position: [1, 2, 3], quaternion: [0, 0, 0, 1], fov: 50, aspect: 16 / 9 }),
    onViewChange: () => () => {}, setGameCameraHelper() {} };
  const { ctx, history, at } = harness(project, { scene });
  assert.deepEqual(project, before, 'load writes nothing');
  assert.equal(K.findShot(ctx, 'fov-only').editable, false, 'a shot without a pose is left to the plain fields');
  assert.equal(plugin.valueControl(ctx, { track: project.tracks[0], event: project.tracks[0].events[1], key: 'fov', value: 40 }), undefined,
    'the plain fov field stays');
  const info = K.findShot(ctx, 'static');
  assert.equal(info.count, 121, 'a static shot gets a 60 Hz grid');
  // The plain field edits the static pose first; the keys then build on it.
  history.apply({ label: 'Edit value', changes: [{ target: { kind: 'event', track: 'camera', event: 'static' }, path: ['values', 'fov'], after: 45 }] });
  at(3);
  K.setChannels(ctx, 'offset', { z: 1 });
  const stat = project.tracks[0].events[0];
  assert.equal(stat.values.keyframes.length, 121);
  nearVector(stat.values.keyframes[0].position, [0, 1.5, 4], 1e-12, 'dolly along -Z');
  assert.equal(stat.values.keyframes[60].fov, 45, 'the static pose as edited is the source');
  assert.equal(plugin.valueControl(ctx, { track: project.tracks[0], event: stat, key: 'fov', value: 35 }), null, 'keys own a baked static shot');
  plugin.revertEvent(ctx, project.tracks[0], stat);
  assert(!('keyframes' in stat.values), 'revert removes the baked samples');
  // An editor-made shot (keys mode, one key from the free view) on a binding-less track.
  const created = K.ensureUserShot(ctx, 10, 14);
  assert(created);
  assert.equal(created.track.id, K.USER_TRACK);
  assert.equal(created.track.binding, undefined);
  assert.equal(created.event.values.keyframes.length, 241);
  assert.equal(project.editor.originals[created.event.id], null, 'marked as added in the editor');
  assert.equal(project.editor.camera.shots[created.event.id].mode, 'keys');
  nearVector(created.event.values.keyframes[100].position, [-1, 2, 3], 1e-12, 'the free view as a rig pose');
  assert.equal(created.event.values.keyframes[100].fov, 50);
  // An editor-made shot is never written natively: it resizes, and its 60 Hz grid follows.
  const resize = (duration) => history.apply({ label: 'Resize clip',
    changes: [{ target: { kind: 'event', track: K.USER_TRACK, event: created.event.id }, path: ['duration'], after: duration }] });
  assert(resize(6));
  assert.equal(created.event.values.keyframes.length, 361, 'a longer clip gets a longer grid');
  created.event.values.keyframes.forEach((sample, index) => assert.equal(sample.time, index / 60, `grid time ${index}`));
  nearVector(created.event.values.keyframes[360].position, [-1, 2, 3], 1e-12, 'the keyed pose holds to the new end');
  assert(resize(1.5));
  assert.equal(created.event.values.keyframes.length, 91, 'a shorter clip gets a shorter grid');
  history.undo();
  history.undo();
  assert.equal(created.event.values.keyframes.length, 241, 'undo brings the original grid back');
  assert.equal(created.event.duration, 4);
  history.undo();
  assert.equal(created.track.events.length, 0, 'undo removes the shot');
  assert.equal(K.ensureUserShot({ ...ctx, project: () => nativeProject() }, 0, 4), null, 'native projects never get new shots');
}

function inspectorAndKeys() {
  const project = nativeProject();
  const { ctx, at } = harness(project, { tab: 'all' });
  at(.5);
  const handled = (key, extra = {}) => plugin.keydown(ctx, { key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...extra });
  assert.equal(handled('k'), false, 'shortcuts only in the Camera/Edit tab or with the panel open');
  const camera = harness(project, { tab: 'camera' });
  camera.at(.5);
  const press = (key, extra = {}) => plugin.keydown(camera.ctx, { key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...extra });
  assert.equal(press('i'), true, 'I adds a key');
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys.map((key) => key.frame), [30]);
  assert(!camera.ctx.edited('cam:0'), 'a zero offset key changes nothing');
  camera.at(1);
  assert.equal(press('d', { ctrlKey: true }), true, 'Ctrl+D duplicates the selected key to the playhead');
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys.map((key) => key.frame), [30, 60]);
  assert.equal(press('['), true);
  near(camera.ctx.time(), .5, 1e-12, '[ goes to the previous key');
  assert.equal(press('Delete'), true, 'Delete removes the selected key');
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys.map((key) => key.frame), [60]);
  assert.equal(press('x'), false);
  assert.equal(press('z', { ctrlKey: true }), false, 'undo stays the host shortcut');
}

// The panel's shot is the scene's (mainCameraAt): a gap between two shots is no shot; past the
// track's last shot a game source holds that shot's final frame.
function playheadGap() {
  const project = nativeProject();
  project.nativeTimeline = false;
  const shots = project.tracks[0].events;
  shots[1].start = 3;   // cam:0 ends at 2, cam:1 starts at 3: a gap
  shots[2].start = 7;   // cam:1 ends at 6, cam:2 ends at 8
  for (const shot of shots) shot.values.postExtrapolationTime = 0;
  const { ctx } = harness(project);
  assert.equal(K.playheadShot(ctx, 2.5), null, 'no shot in a gap between shots');
  assert.equal(K.playheadShot(ctx, 6.5), null, 'nor in the next gap');
  const held = K.playheadShot(ctx, 9);
  assert.equal(held && held.event.id, 'cam:2', 'past the last shot the game source holds it');
  assert.equal(held.frame, 60, 'on its last frame');
  project.source = { kind: 'mod' };
  assert.equal(K.playheadShot(ctx, 9), null, 'other sources hold nothing');
  project.source = { kind: 'game' };
  // A Hold extrapolation bridges the cut, as in the scene.
  shots[0].values.postExtrapolationMode = 1;
  shots[0].values.postExtrapolationTime = 1;
  assert.equal(K.playheadShot(ctx, 2.5).event.id, 'cam:0', 'a Hold post-extrapolation keeps the shot');
}

// A key that moves without changing the samples (a lone offset key) still redraws its lane's
// diamonds, on the edit and on undo/redo.
function keyLaneRefresh() {
  const project = nativeProject();
  const { ctx, history, log, at } = harness(project);
  at(.5);
  K.setChannels(ctx, 'offset', { z: 1 });
  const arrays = project.tracks[0].events[0].values.keyframes;
  log.refreshed.length = 0;
  assert(K.moveKey(ctx, 'cam:0', 30, 40));
  assert.equal(project.tracks[0].events[0].values.keyframes, arrays, 'the samples are not rewritten');
  assert.deepEqual(log.refreshed, ['cam'], 'the lane is redrawn once');
  history.undo();
  history.redo();
  assert.deepEqual(log.refreshed, ['cam', 'cam', 'cam'], 'and on undo and redo');
  K.setChannels(ctx, 'offset', { z: 2 });
  assert.deepEqual(log.refreshed, ['cam', 'cam', 'cam', 'cam'], 'a rebake that redraws the lane is not doubled');
}

// K/I/D/[/] by physical key when event.key is not Latin (Korean or Japanese input on).
function imeShortcuts() {
  const project = nativeProject();
  const { ctx, at } = harness(project, { tab: 'camera' });
  at(.5);
  const press = (key, code, extra = {}) => plugin.keydown(ctx, { key, code, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...extra });
  assert.equal(press('ㅑ', 'KeyI'), true, 'Hangul ㅑ on the I key adds a key');
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys.map((key) => key.frame), [30]);
  at(1);
  assert.equal(press('ㅇ', 'KeyD', { ctrlKey: true }), true, 'Ctrl+D on the D key duplicates');
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys.map((key) => key.frame), [30, 60]);
  assert.equal(press('Process', 'BracketLeft'), true, 'an IME "Process" key on [ goes to the previous key');
  near(ctx.time(), .5, 1e-12, 'at the previous key');
  assert.equal(press('Process', 'BracketRight'), true);
  near(ctx.time(), 1, 1e-12, '] goes to the next key');
  assert.equal(press('ㅏ', 'KeyK'), true, 'Hangul ㅏ on the K key is Key current view');
  assert.equal(press('ㅌ', 'KeyX'), false, 'other keys are left alone');
  // A Latin key wins over its physical position (AZERTY and similar layouts).
  assert.equal(press('a', 'KeyI'), false, 'event.key decides when it is Latin');
}

// Typed values stay inside what the bake and the native writer accept.
function valueLimits() {
  const project = nativeProject();
  const { ctx, at } = harness(project);
  const shot = event(project, 'cam:0'), before = original('cam:0');
  at(.5);
  K.setChannels(ctx, 'offset', { fov: 500 });
  let key = project.editor.camera.shots['cam:0'].keys[0];
  near(key.values.fov, 170 - before[30].fov, 1e-12, 'an offset FOV is cut where the result reaches 170');
  near(shot.values.keyframes[30].fov, 170, 1e-12, 'the result at the key is 170');
  K.setChannels(ctx, 'offset', { fov: -500 });
  key = project.editor.camera.shots['cam:0'].keys[0];
  near(key.values.fov, 1 - before[30].fov, 1e-12, 'and where it reaches 1');
  K.setChannels(ctx, 'offset', { fov: 0, z: 5e6 });
  key = project.editor.camera.shots['cam:0'].keys[0];
  assert.equal(key.values.z, 1e6, 'a position offset is cut at 1e6 m');
  for (const sample of shot.values.keyframes) assert(sample.position.every((value) => Math.abs(value) <= 1e6), 'baked positions stay within ±1e6 m');
  K.setChannels(ctx, 'absolute', { x: -7e6 });
  for (const sample of shot.values.keyframes) assert(sample.position.every((value) => Math.abs(value) <= 1e6), 'also from the Result row');
  // Keys mode: absolute FOV in [1, 170], positions within ±1e6 m.
  K.setMode(ctx, 'keys', { confirm: false });
  K.setChannels(ctx, 'absolute', { fov: 900, y: 2e7 });
  key = project.editor.camera.shots['cam:0'].keys.find((item) => item.frame === 30);
  assert.equal(key.values.fov, 170);
  assert.equal(key.values.y, 1e6);
}

// A record whose clip was deleted goes with the next camera command, in the same undo step.
function orphanRecords() {
  const project = { version: 1, name: 'Mod MV', duration: 20, nativeTimeline: false, tracks: [
    { id: 'camera', kind: 'camera', binding: 'MainCamera', label: 'Camera', events: [
      { id: 'static', start: 2, duration: 2, values: { position: [0, 1.5, 5], rotation: [0, 0, 0, 1], fov: 35 }, editableValues: ['fov', 'position', 'rotation'] }] }] };
  const scene = { getViewPose: () => ({ mode: 'orbit', position: [1, 2, 3], quaternion: [0, 0, 0, 1], fov: 50, aspect: 16 / 9 }),
    onViewChange: () => () => {}, setGameCameraHelper() {} };
  const { ctx, history, at } = harness(project, { scene });
  const created = K.ensureUserShot(ctx, 10, 12);
  const id = created.event.id;
  const userTrack = created.track;
  history.apply({ label: 'Delete clip', changes: [{ target: { kind: 'track', track: userTrack.id }, path: ['events'], op: 'remove', index: 0 }] });
  assert.deepEqual(Object.keys(project.editor.camera.shots), [id], 'the delete itself leaves the record');
  at(3);
  assert(K.setChannels(ctx, 'offset', { y: .5 }));
  assert.deepEqual(Object.keys(project.editor.camera.shots), ['static'], 'the next camera edit drops the orphan');
  history.undo();
  assert.deepEqual(Object.keys(project.editor.camera.shots), [id], 'undo brings it back');
  history.undo();
  assert.equal(userTrack.events.length, 1, 'and undoing the delete restores the clip with its record');
  assert.equal(project.editor.camera.shots[id].mode, 'keys');
  // A new shot never reuses the id of a record still held.
  history.apply({ label: 'Delete clip', changes: [{ target: { kind: 'track', track: userTrack.id }, path: ['events'], op: 'remove', index: 0 }] });
  const next = K.ensureUserShot(ctx, 14, 16);
  assert.notEqual(next.event.id, id, 'a fresh id');
  assert.deepEqual(Object.keys(project.editor.camera.shots), [next.event.id], 'the new shot command drops the orphan too');
  // Nor the id of a deleted clip without a record (a duplicate never edited): editor.originals
  // keeps it, and the host's Duplicate clip follows the same rule.
  const dup = hostDuplicate(project, history, userTrack.id, next.event.id);
  assert.equal(project.editor.camera.shots[dup.id], undefined);
  history.apply({ label: 'Delete clip', changes: [{ target: { kind: 'track', track: userTrack.id }, path: ['events'], op: 'remove',
    index: userTrack.events.indexOf(dup) }] });
  const third = K.ensureUserShot(ctx, 17, 19);
  assert(![id, next.event.id, dup.id].includes(third.event.id), `an id never held (${third.event.id})`);
}

// The host's Duplicate clip (mv-studio.js duplicateEvent) as one insert command: a copy with an
// id <track>:u<n> the project never held, placed at the source's end. History marks it added
// (originals null). The browser test runs the real one.
function hostDuplicate(project, history, trackId, eventId) {
  const owner = project.tracks.find((item) => item.id === trackId);
  const source = owner.events.find((item) => item.id === eventId);
  const ids = new Set(project.tracks.flatMap((item) => item.events.map((clip) => clip.id)));
  let number = 1;
  while (ids.has(`${owner.id}:u${number}`) || history.originals.get(`${owner.id}:u${number}`) !== undefined) number++;
  const clone = copy(source);
  clone.id = `${owner.id}:u${number}`;
  clone.start = source.start + source.duration;
  delete clone.editable;
  assert(history.apply({ label: 'Duplicate clip', changes: [{ target: { kind: 'track', track: owner.id }, path: ['events'], op: 'insert',
    index: owner.events.indexOf(source) + 1, value: clone }] }));
  return owner.events.find((item) => item.id === clone.id);
}

// Samples of a moving shot at `rate` Hz, the importer's way: ceil(duration·rate)+1 of them, the
// last one at the clip's end.
function movingSamples(duration, rate) {
  const count = Math.ceil(duration * rate - 1e-9) + 1;
  return Array.from({ length: count }, (_, index) => {
    const time = Math.min(index / rate, duration), s = time / duration;
    return { time, position: [10 - 2 * s, 3.35 + .1 * Math.sin(5 * s), 30 - 4 * s],
      rotation: M.normalize(M.eulerZXYToQuaternion({ pan: 160 + 30 * s, tilt: -3, roll: 0 })), fov: 28 + 2 * s };
  });
}

// A clip added by Duplicate clip carries its samples, not keys: they are its only motion, so no
// rebake, resize or undo rewrites them (30 Hz and off-grid clips included). A shot whose keys own
// its pose takes the 60 Hz grid of its length, and undoing a resize gives its samples back.
function duplicatedClips() {
  const modProject = (duration, rate) => ({ version: 1, name: 'Mod MV', duration: 30, nativeTimeline: false, source: { kind: 'mod' }, tracks: [
    { id: 'cam', kind: 'camera', binding: '/EntryPoint/Live/Cameras/MainCamera', nativeClass: 'AnimationTrack', label: 'Camera', events: [
      { id: 'cam:0', start: 0, duration, values: { keyframes: movingSamples(duration, rate) }, editableValues: ['keyframes'] }] }] });
  const resize = (history, trackId, id, duration) => assert(history.apply({ label: 'Resize clip',
    changes: [{ target: { kind: 'event', track: trackId, event: id }, path: ['duration'], after: duration }] }));
  for (const [duration, rate, name] of [[4, 60, '60 Hz'], [4, 30, '30 Hz'], [3.205, 60, 'off-grid 3.205 s']]) {
    const project = modProject(duration, rate);
    const { ctx, history } = harness(project);
    const source = copy(project.tracks[0].events[0].values.keyframes);
    const dup = hostDuplicate(project, history, 'cam', 'cam:0');
    const arrays = dup.values.keyframes;
    assert.equal(K.findShot(ctx, dup.id).user, true, `${name}: an added clip`);
    assert.equal(K.findShot(ctx, dup.id).owned, false, `${name}: no keys own it`);
    assert.deepEqual(dup.values.keyframes, source, `${name}: the duplicate carries the samples`);
    K.requestBake(ctx, {});
    assert.equal(dup.values.keyframes, arrays, `${name}: a rebake leaves them alone`);
    resize(history, 'cam', dup.id, duration / 2);
    assert.equal(dup.values.keyframes, arrays, `${name}: a shrink does not cut them`);
    history.undo();
    assert.equal(dup.duration, duration);
    assert.equal(dup.values.keyframes, arrays, `${name}: undo leaves them as they were`);
    assert.deepEqual(dup.values.keyframes, source, `${name}: bit for bit`);
    history.redo();
    history.undo();
    assert.deepEqual(dup.values.keyframes, source, `${name}: after redo and undo too`);
  }
  // A shot made in the editor: its keys own the pose, so its grid follows the clip.
  const project = { version: 1, name: 'Mod MV', duration: 30, nativeTimeline: false, source: { kind: 'mod' }, tracks: [] };
  const { ctx, history, at } = harness(project);
  const made = K.ensureUserShot(ctx, 0, 4);
  at(3);
  assert(K.setChannels(ctx, 'absolute', { x: 5 }), 'a second key: the shot moves');
  const keyed = copy(made.event.values.keyframes);
  assert.equal(K.findShot(ctx, made.event.id).owned, true);
  resize(history, K.USER_TRACK, made.event.id, 1);
  assert.equal(made.event.values.keyframes.length, 61, 'a shorter grid');
  history.undo();
  assert.deepEqual(made.event.values.keyframes, keyed, 'undo bakes the same samples again');
  resize(history, K.USER_TRACK, made.event.id, 3.205);
  const grid = made.event.values.keyframes;
  assert.equal(grid.length, 194, 'an off-grid length gets the importer grid: ceil(3.205·60)+1 samples');
  assert.equal(grid.at(-1).time, 3.205, 'the last one at the clip end');
  grid.slice(0, -1).forEach((sample, index) => assert.equal(sample.time, index / 60, `grid time ${index}`));
  near(grid[180].position[0], 5, 1e-12, 'the keys are on the same frames');
  history.undo();
  assert.deepEqual(made.event.values.keyframes, keyed);
  // Its duplicate carries the baked samples and no keys: shrink and undo give them back.
  const dup = hostDuplicate(project, history, K.USER_TRACK, made.event.id);
  resize(history, K.USER_TRACK, dup.id, 1);
  history.undo();
  assert.deepEqual(dup.values.keyframes, keyed, 'the duplicate of a keyed shot keeps its motion');
}

// The first edit of an added clip claims it: its motion becomes keys on its 60 Hz grid, so later
// rebakes start from the keys, not from the clip's own last bake (no stacking). Undo gives the
// clip its samples back bit for bit; a record that does not own the pose is never baked.
function claimDuplicatedClip() {
  const modProject = (duration, rate) => ({ version: 1, name: 'Mod MV', duration: 30, nativeTimeline: false, source: { kind: 'mod' }, tracks: [
    { id: 'cam', kind: 'camera', binding: '/EntryPoint/Live/Cameras/MainCamera', nativeClass: 'AnimationTrack', label: 'Camera', events: [
      { id: 'cam:0', start: 0, duration, values: { keyframes: movingSamples(duration, rate) }, editableValues: ['keyframes'] }] }] });
  const close = (actual, expected, message) => {
    nearVector(actual.position, expected.position, 2.5e-3, `${message} position`);
    assert(angle(actual.rotation, expected.rotation) < .1, `${message} rotation`);
    near(actual.fov, expected.fov, .02, `${message} fov`);
  };
  {
    const project = modProject(4, 60);
    const { ctx, history, at } = harness(project);
    const dup = hostDuplicate(project, history, 'cam', 'cam:0');
    const source = copy(dup.values.keyframes);
    at(dup.start + .5);
    assert(K.setChannels(ctx, 'absolute', { y: 4 }), 'the Value row of an added clip');
    const record = project.editor.camera.shots[dup.id];
    assert.equal(record.mode, 'keys', 'the first edit gives the clip keys');
    assert(record.keys.length >= 3 && record.keys.some((key) => key.frame === 30), `its motion as keys plus the edit (${record.keys.length})`);
    assert.equal(K.findShot(ctx, dup.id).owned, true);
    assert.equal(dup.values.keyframes[30].position[1], 4);
    close(dup.values.keyframes[0], source[0], 'first frame');
    close(dup.values.keyframes[240], source[240], 'last frame');
    close(dup.values.keyframes[150], source[150], 'away from the edit');
    const baked = copy(dup.values.keyframes);
    K.requestBake(ctx, {});
    assert.deepEqual(dup.values.keyframes, baked, 'a rebake starts from the keys: nothing stacks');
    at(dup.start + 3);
    assert(K.setChannels(ctx, 'absolute', { x: 9 }));
    assert.equal(dup.values.keyframes[30].position[1], 4, 'a second key leaves the first edit as it was');
    // The offset row (API only: the panel shows the Value row for added clips) writes keys too.
    at(dup.start + 2);
    assert(K.setChannels(ctx, 'offset', { z: 27 }));
    K.requestBake(ctx, {});
    assert.equal(dup.values.keyframes[120].position[2], 27, 'and stays put across rebakes');
    history.undo();
    history.undo();
    assert.deepEqual(dup.values.keyframes, baked);
    history.undo();
    assert.deepEqual(dup.values.keyframes, source, 'undoing the first edit gives the samples back bit for bit');
    assert.equal(project.editor.camera?.shots?.[dup.id], undefined);
    assert.equal(K.findShot(ctx, dup.id).owned, false);
    history.redo();
    assert.deepEqual(dup.values.keyframes, baked, 'redo bakes the same samples');
    history.undo();
    // Add key claims the clip even on a frame its keys already hold.
    at(dup.start);
    assert(K.addKey(ctx), 'Add key on an added clip is an edit');
    assert.equal(project.editor.camera.shots[dup.id].mode, 'keys');
    history.undo();
    assert.deepEqual(dup.values.keyframes, source);
    // A record that does not own the pose (an offset record of an older session) is not baked.
    assert(history.apply({ label: 'Edit camera key', changes: [{ target: { kind: 'editor' }, path: ['camera', 'shots', dup.id],
      after: { mode: 'offset', space: 'view', keys: [{ frame: 30, values: { x: 0, y: 1, z: 0, pan: 0, tilt: 0, roll: 0, fov: 0 }, interp: 'bezier', handle: 'auto-clamped' }] } }] }));
    K.requestBake(ctx, {});
    K.requestBake(ctx, {});
    assert.deepEqual(dup.values.keyframes, source, 'an offset record on an added clip bakes nothing');
    at(dup.start + .5);
    assert(K.setChannels(ctx, 'absolute', { y: 4 }));
    assert.equal(project.editor.camera.shots[dup.id].mode, 'keys', 'the next edit replaces it with keys');
    assert.equal(dup.values.keyframes[30].position[1], 4);
  }
  {
    // A 30 Hz clip: claimed on the 60 Hz grid, its motion kept by time.
    const project = modProject(4, 30);
    const { ctx, history, at } = harness(project);
    const dup = hostDuplicate(project, history, 'cam', 'cam:0');
    const source = copy(dup.values.keyframes);
    at(dup.start + 1);
    assert(K.setChannels(ctx, 'absolute', { fov: 40 }));
    assert.equal(dup.values.keyframes.length, 241, 'the 60 Hz grid of 4 s');
    dup.values.keyframes.forEach((sample, index) => assert.equal(sample.time, index / 60, `grid time ${index}`));
    assert.equal(dup.values.keyframes[60].fov, 40, 'the key at 1 s');
    for (const frame of [0, 15, 150, 211, 240]) close(dup.values.keyframes[frame], M.sampleFrames(source, frame / 60), `30 Hz motion at ${frame / 60} s`);
    K.requestBake(ctx, {});
    assert.equal(dup.values.keyframes[60].fov, 40);
    history.undo();
    assert.deepEqual(dup.values.keyframes, source, 'undo gives the 30 Hz samples back');
  }
}

// Several keys at once: the selection (one shot at a time), group moves (clamped, never onto or
// past an unselected key), a value change on every selected key, time stretch, delete, copy and
// paste (clipped to the shot, across modes) and the numeric offset; each one undo step, and undo
// and redo give back the records and the selection exactly.
function multiKeys() {
  // Pure planning: bounds and stretch.
  const keyList = (frames) => frames.map((frame) => ({ frame }));
  assert.deepEqual(K.moveBounds(keyList([0, 10, 20, 30]), [10, 20], 41), { low: -9, high: 9 }, 'between the unselected neighbours');
  assert.deepEqual(K.moveBounds(keyList([5, 10]), [5, 10], 41), { low: -5, high: 30 }, 'inside the shot');
  let plan = K.planScale(keyList([0, 10, 20, 30]), [10, 20], 40, 41);
  assert.equal(plan.end, 29, 'a stretch stops before the next unselected key');
  assert.deepEqual([...plan.mapping], [[10, 10], [20, 29]]);
  plan = K.planScale(keyList([10, 20, 30]), [10, 20, 30], 10, 41);
  assert.deepEqual([...plan.mapping.values()], [10, 11, 12], 'a full compression keeps one frame between keys');
  assert.equal(K.planScale(keyList([10, 11]), [10, 11], 5, 41), null, 'nothing left to compress');

  const project = nativeProject();
  const { ctx, history, log, at } = harness(project);
  const shot = event(project, 'cam:1'), start = shot.start;
  const frameAt = (frame) => start + frame / 60;
  for (const [frame, y] of [[0, 0], [20, .2], [40, .4], [60, .6], [100, 1]]) assert(K.setChannels(ctx, 'offset', { y }, { time: frameAt(frame) }));
  const record = () => project.editor.camera.shots['cam:1'];
  const frames = () => record().keys.map((key) => key.frame);
  const ys = () => record().keys.map((key) => key.values.y);
  const selection = () => K.selected(ctx) && K.selected(ctx).frames;

  // Selection: a box (replace), toggles, one shot at a time.
  K.selectKeys(ctx, 'cam:1', [20, 40, 60]);
  assert.deepEqual(selection(), [20, 40, 60]);
  K.toggleKey(ctx, 'cam:1', 100);
  assert.deepEqual(selection(), [20, 40, 60, 100], 'a toggle adds');
  K.toggleKey(ctx, 'cam:1', 40);
  assert.deepEqual(selection(), [20, 60, 100], 'and removes');
  at(.5);
  K.setChannels(ctx, 'offset', { x: .1 });
  assert.deepEqual(K.selected(ctx), { event: 'cam:0', frames: [30], frame: 30 }, 'an edit selects its key');
  K.selectKeys(ctx, 'cam:1', [20, 40]);
  log.reports.length = 0;
  K.toggleKey(ctx, 'cam:0', 30);
  assert.deepEqual(K.selected(ctx).frames, [30], 'a key of another shot starts a new selection');
  assert.deepEqual(log.reports, [['Keys can be selected in one camera shot at a time.', false]]);
  assert(K.selectAllKeys(ctx, K.findShot(ctx, 'cam:1')));
  assert.deepEqual(selection(), [0, 20, 40, 60, 100], 'select all keys of a shot');
  assert(K.clearSelection(ctx));
  assert.equal(K.selected(ctx), null);

  // Group move: same delta for all, stopped by the next unselected key, then by the shot's ends.
  K.selectKeys(ctx, 'cam:1', [20, 40]);
  let undo = history.size().undo;
  const before = copy(record());
  assert.equal(K.moveKeys(ctx, 'cam:1', [20, 40], 30), 19, 'stops one frame before the key at 60');
  assert.deepEqual(frames(), [0, 39, 59, 60, 100]);
  assert.deepEqual(ys(), [0, .2, .4, .6, 1], 'values and order move with the keys');
  assert.equal(history.size().undo, undo + 1, 'one undo step');
  assert.equal(history.peekUndo().label, 'Move camera keys');
  assert.deepEqual(selection(), [39, 59], 'the selection follows');
  assert.equal(K.moveKeys(ctx, 'cam:1', [39, 59], -100), -38, 'and one frame after the key at 0');
  assert.deepEqual(frames(), [0, 1, 21, 60, 100]);
  assert.equal(K.moveKeys(ctx, 'cam:1', [1, 21], -1), 0, 'a collision is refused, not merged');
  assert.equal(history.size().undo, undo + 2);
  K.selectKeys(ctx, 'cam:1', [60, 100]);
  assert.equal(K.moveKeys(ctx, 'cam:1', [60, 100], 500), 80, 'the last key stops at the shot end');
  assert.deepEqual(frames(), [0, 1, 21, 140, 180]);
  // Undo and redo: the records and the selection made with them.
  const moved = copy(record());
  history.undo();
  assert.deepEqual(selection(), [60, 100], 'undo selects the keys as they were');
  history.undo();
  assert.deepEqual(selection(), [39, 59]);
  history.undo();
  assert.deepEqual(record(), before, 'undo restores the record exactly');
  assert.deepEqual(selection(), [20, 40]);
  history.redo(); history.redo(); history.redo();
  assert.deepEqual(record(), moved, 'redo too');
  assert.deepEqual(selection(), [140, 180]);

  // Value change on every selected key (the curve view's drag): free handles stay relative.
  K.selectKey(ctx, 'cam:1', 21);
  K.setKeyProperty(ctx, 'handle', 'free');
  const handles = copy(record().keys[2].handles), freed = copy(record());
  K.selectKeys(ctx, 'cam:1', [1, 21, 140]);
  undo = history.size().undo;
  const token = history.begin('Move camera keys');
  const base = copy(record());
  K.moveKeys(ctx, 'cam:1', [1, 21, 140], 5, { channel: 'y', change: .5, base });
  K.moveKeys(ctx, 'cam:1', [1, 21, 140], 2, { channel: 'y', change: .25, base });
  history.end(token);
  assert.equal(history.size().undo, undo + 1, 'a curve drag is one undo step');
  assert.deepEqual(frames(), [0, 3, 23, 142, 180], 'each move starts from the record the drag began with');
  ys().forEach((value, index) => near(value, [0, .45, .65, .85, 1][index], 1e-12, `y of key ${index}`));
  assert.deepEqual(record().keys[2].handles, handles, 'handles are relative to their key');
  history.undo();
  assert.deepEqual(record(), freed, 'undo of the drag');
  assert.deepEqual(selection(), [1, 21, 140], 'and its selection');

  // Time stretch around the first selected key, stopped before an unselected key.
  K.selectKeys(ctx, 'cam:1', [1, 21]);
  K.moveKeys(ctx, 'cam:1', [1, 21], 9);
  assert.deepEqual(frames(), [0, 10, 30, 140, 180]);
  K.selectKeys(ctx, 'cam:1', [10, 30, 140]);
  undo = history.size().undo;
  log.reports.length = 0;
  plan = K.scaleKeys(ctx, 1.5);
  assert.deepEqual(frames(), [0, 10, 36, 179, 180], 'pulled back to the frame before the key at 180');
  assert.equal(plan.end, 179);
  assert.deepEqual(log.reports, [['The timing stops at a neighbouring key or the end of the shot.', false]]);
  assert.equal(history.peekUndo().label, 'Scale camera key timing');
  near(record().keys[2].handles.y.out[0], handles.y.out[0] * 169 / 130, 1e-12, 'free handles scale their time with the keys');
  K.scaleKeys(ctx, .5);
  assert.deepEqual(frames(), [0, 10, 23, 95, 180], 'compress: half the spacing');
  assert.deepEqual(selection(), [10, 23, 95]);
  assert.equal(history.size().undo, undo + 2);
  assert.equal(K.scaleKeys(ctx, .001) && frames().slice(1, 4).join(), '10,11,12', 'a full compression snaps to consecutive frames');
  history.undo();
  assert.deepEqual(frames(), [0, 10, 23, 95, 180]);
  K.selectKeys(ctx, 'cam:1', [10]);
  assert.equal(K.scaleKeys(ctx, 2), false, 'one key has no timing to scale');

  // Numeric offset added to every selected key; FOV stays within what the bake accepts.
  K.selectKeys(ctx, 'cam:1', [10, 23]);
  const keyBefore = copy(record().keys);
  assert(K.offsetKeys(ctx, { x: .5, pan: -10, fov: 500, y: 0 }));
  assert.equal(history.peekUndo().label, 'Offset camera keys');
  const sample = original('cam:1');
  record().keys.forEach((key, index) => {
    const was = keyBefore[index].values;
    if (key.frame === 10 || key.frame === 23) {
      near(key.values.x, was.x + .5, 1e-12, 'x + 0.5');
      near(key.values.pan, was.pan - 10, 1e-12, 'pan - 10');
      near(key.values.y, was.y, 0, 'y unchanged');
      near(key.values.fov, 170 - sample[key.frame].fov, 1e-12, 'FOV offset cut where the result reaches 170');
    } else assert.deepEqual(key.values, was, 'other keys unchanged');
  });

  // Copy, then paste at the playhead of another shot: relative timing, clipped to the shot.
  K.selectKeys(ctx, 'cam:1', [10, 23, 95]);
  assert(K.copyKeys(ctx));
  const copied = record().keys.filter((key) => [10, 23, 95].includes(key.frame)).map((key) => key.values);
  at(100 / 60);
  log.reports.length = 0;
  undo = history.size().undo;
  assert.equal(K.pasteKeys(ctx), 2, 'two of three copied keys fit in cam:0 (frames 100, 113; 185 is past 120)');
  assert.equal(history.size().undo, undo + 1);
  assert.equal(history.peekUndo().label, 'Paste camera keys');
  assert.deepEqual(log.reports, [['Keys outside this shot were left out: 1.', false]]);
  const pasted = project.editor.camera.shots['cam:0'].keys;
  assert.deepEqual(pasted.map((key) => key.frame), [30, 100, 113]);
  // The same offsets (same mode and space); a FOV offset is cut where this shot's FOV reaches 170.
  const withoutFov = (values) => ({ ...values, fov: undefined });
  assert.deepEqual(pasted.slice(1).map((key) => withoutFov(key.values)), copied.slice(0, 2).map(withoutFov), 'the same offsets');
  pasted.slice(1).forEach((key, index) => near(key.values.fov, Math.min(copied[index].fov, 170 - original('cam:0')[key.frame].fov), 1e-12, 'FOV within range'));
  assert.deepEqual(K.selected(ctx), { event: 'cam:0', frames: [100, 113], frame: 100 }, 'the pasted keys are selected');
  // Paste over existing keys replaces them (never two keys on a frame).
  at(30 / 60);
  K.pasteKeys(ctx);
  assert.deepEqual(project.editor.camera.shots['cam:0'].keys.map((key) => key.frame), [30, 43, 100, 113, 115]);
  assert.deepEqual(withoutFov(project.editor.camera.shots['cam:0'].keys[0].values), withoutFov(copied[0]), 'the key at 30 is replaced');
  // Into a keyframe shot: the copied camera pose is kept.
  const sourcePose = copy(shot.values.keyframes[10]);
  at(event(project, 'cam:2').start + 5 / 60);
  assert(K.setMode(ctx, 'keys', { confirm: false }));
  K.pasteKeys(ctx);
  const target = event(project, 'cam:2').values.keyframes[5];
  nearVector(target.position, sourcePose.position, 1e-9, 'pasted pose position');
  assert(angle(target.rotation, sourcePose.rotation) < 1e-6, 'pasted pose rotation');
  near(target.fov, sourcePose.fov, 1e-9, 'pasted pose FOV');
  assert.deepEqual(project.editor.camera.shots['cam:2'].keys.map((key) => key.frame), [0, 5, 18, 60]);
  history.undo();
  assert.deepEqual(project.editor.camera.shots['cam:2'].keys.map((key) => key.frame), [0, 60], 'undo removes the pasted keys');

  // Delete the selection (one step); undo brings back keys and selection.
  K.selectKeys(ctx, 'cam:1', [10, 23]);
  const kept = copy(record());
  assert(K.deleteKeys(ctx));
  assert.deepEqual(frames(), [0, 95, 180]);
  assert.equal(history.peekUndo().label, 'Delete camera keys');
  assert.equal(K.selected(ctx), null);
  history.undo();
  assert.deepEqual(record(), kept);
  assert.deepEqual(selection(), [10, 23]);

  // Shortcuts (Camera tab): Escape, Ctrl+C, Ctrl+V, Delete; Ctrl+C with page text selected is the browser's.
  const press = (key, extra = {}) => plugin.keydown(ctx, { key, code: '', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...extra });
  assert.equal(press('Escape'), true);
  assert.equal(K.selected(ctx), null);
  assert.equal(press('Escape'), false, 'nothing to clear');
  K.selectKeys(ctx, 'cam:1', [95, 180]);
  assert.equal(press('c', { ctrlKey: true }), true);
  at(event(project, 'cam:1').start);
  undo = history.size().undo;
  assert.equal(press('ㅍ', { code: 'KeyV', metaKey: true }), true, 'Cmd+V by physical key with Hangul input');
  assert.deepEqual(frames(), [0, 10, 23, 85, 95, 180], 'pasted at frames 0 (replacing that key) and 85');
  assert.equal(history.size().undo, undo + 1);
  K.selectKeys(ctx, 'cam:1', [10, 23]);
  assert.equal(press('Delete'), true);
  assert.deepEqual(frames(), [0, 85, 95, 180], 'Delete removes every selected key');
  globalThis.getSelection = () => 'some text';
  K.selectKeys(ctx, 'cam:1', [0]);
  assert.equal(press('c', { ctrlKey: true }), false, 'page text selected: the browser copies it');
  delete globalThis.getSelection;
}

(async () => {
  unedited();
  offsetKey();
  interpolation();
  keysMode();
  await followsMove();
  layers();
  await asyncLayers();
  keyView();
  subCameras();
  await followCoversMainShot();
  extrapolation();
  hemisphere();
  absoluteEdit();
  simplifyShot();
  nonNative();
  inspectorAndKeys();
  keyLaneRefresh();
  playheadGap();
  imeShortcuts();
  valueLimits();
  orphanRecords();
  duplicatedClips();
  claimDuplicatedClip();
  multiKeys();
  console.log('mv studio camera keys tests passed');
})().catch((error) => { console.error(error); process.exit(1); });
