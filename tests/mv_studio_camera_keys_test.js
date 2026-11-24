/* MV Studio camera keys (mv-studio-camera-keys.js) on a stub editor context with the
   real undo history: no record → the original samples; one offset key moves every
   sample of the shot; linear/constant/bezier keys; the at-playhead edit creates or
   updates the key at round(local·60) (the snap-back fix); keys follow a moved shot;
   revert; the duration lock; a layer at order 30 sees the keyed pose; undo/redo
   rebakes identical arrays; Key current view (aspect correction and LiveCameraOffset);
   quaternion hemisphere continuity; static and editor-made shots of non-native
   projects; simplify; async layers; and the no-regression rule: an unedited project is
   never written to and gets no project.editor. */
'use strict';
const assert = require('node:assert/strict');
globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-split.js');
require('../webtools/web/static/mv-studio-camera-math.js');
require('../webtools/web/static/mv-studio-edit-history.js');
require('../webtools/web/static/mv-studio-timeline-interact.js');
require('../webtools/web/static/mv-studio-camera-keys.js');
const M = globalThis.MVStudioCameraMath, K = globalThis.MVStudioCameraKeys, H = globalThis.MVStudioEditHistory;
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
  for (const shot of fresh.tracks[0].events) {
    assert.equal(plugin.clipConstraints(second.ctx, fresh.tracks[0], shot), undefined, 'unedited shots resize');
    assert.equal(K.differs(second.ctx, shot), false);
  }
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
  assert.deepEqual(plugin.clipConstraints(ctx, track(project, 'cam'), shot), { resize: false, reason: 'Duration is locked while this shot has camera edits.' });
  assert.equal(plugin.clipConstraints(ctx, track(project, 'cam'), other), undefined);

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
  // A shot whose length differs from the original cannot be keyed, and export refuses.
  history.apply({ label: 'Resize clip', changes: [{ target: { kind: 'event', track: 'cam', event: 'cam:1' }, path: ['duration'], after: shot.duration + .5 }] });
  const info = K.findShot(ctx, 'cam:1');
  assert.equal(info.editable, false);
  assert.equal(info.reason, "Restore this shot's original length to edit its camera.");
  return plugin.beforeExport(ctx).then(() => assert.fail('export must refuse'), (error) => {
    assert.equal(error.message, 'Restore the original length of camera shots with camera edits before exporting.');
  });
}

function layers() {
  const project = nativeProject();
  const { ctx, history, at } = harness(project);
  const shot = event(project, 'cam:0'), before = original('cam:0');
  let seen = null;
  const remove = K.registerLayer({ id: 'probe', order: 30, affects: (context, item) => item.event.id === 'cam:0',
    apply(context, item, frames) {
      seen = { first: frames[0].position.slice(), t: frames[10].t, count: frames.length };
      for (const frame of frames) frame.position = [frame.position[0], frame.position[1] + .5, frame.position[2]];
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
  assert(plugin.clipConstraints(ctx, created.track, created.event), 'an editor shot with keys keeps its length');
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

(async () => {
  unedited();
  offsetKey();
  interpolation();
  keysMode();
  await followsMove();
  layers();
  await asyncLayers();
  keyView();
  hemisphere();
  absoluteEdit();
  simplifyShot();
  nonNative();
  inspectorAndKeys();
  console.log('mv studio camera keys tests passed');
})().catch((error) => { console.error(error); process.exit(1); });
