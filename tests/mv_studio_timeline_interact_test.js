/* MV Studio clip interaction (mv-studio-timeline-interact.js): frame, playhead and
   edge snaps with Alt, move/trim clamps, one commit per drag with Escape cancelling,
   blocked resize, Alt+arrow nudges, and the port of Unity's
   CalculateExtrapolationTimes against every stored value of the 12035 timeline. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

globalThis.window = globalThis;
const frames = [];
globalThis.requestAnimationFrame = (callback) => { frames.push(callback); return frames.length; };
globalThis.cancelAnimationFrame = () => {};
const listeners = {};
globalThis.addEventListener = (type, listener) => { (listeners[type] ||= []).push(listener); };
globalThis.removeEventListener = (type, listener) => { listeners[type] = (listeners[type] || []).filter((item) => item !== listener); };
require('../webtools/web/static/mv-studio-timeline-interact.js');
const I = globalThis.MVStudioTimelineInteract;
const flush = () => { while (frames.length) frames.shift()(); };
const near = (actual, expected, message) => assert(Math.abs(actual - expected) < 1e-9, `${message}: ${actual} != ${expected}`);

function snapping() {
  const options = { pixelsPerSecond: 60, targets: [2.3], radius: 6 };
  near(I.snapTime(1.004, options).time, 1, 'the frame grid always applies');
  near(I.snapTime(2.25, options).time, 2.3, 'a target within 6 px wins');
  near(I.snapTime(2.15, options).time, 2.15, '9 px away: no target, frame grid only');
  near(I.snapTime(2.25, { ...options, alt: true }).time, 2.25, 'Alt keeps only the frame grid');
  near(I.snapTime(2.29, { pixelsPerSecond: 60, targets: [2.31, 2.284] }).time, 137 / 60, 'nearest target, then the frame grid');

  const bounds = { min: 0, max: 10, minLength: 1 / 60 };
  // Move: either edge may snap; the nearer one wins.
  let moved = I.moveRange({ start: 1, end: 3 }, 2.25, { pixelsPerSecond: 48, targets: [5.3], bounds });
  near(moved.start, 3.3, 'the end edge snaps to 5.3');
  near(moved.end - moved.start, 2, 'a move keeps the length');
  moved = I.moveRange({ start: 1, end: 3 }, .02, { pixelsPerSecond: 48, targets: [], bounds });
  near(moved.start, 1.0166666666666666, 'frame aligned start');
  moved = I.moveRange({ start: 1, end: 3 }, 50, { pixelsPerSecond: 48, targets: [], bounds });
  near(moved.start, 8, 'clamped to the MV end');
  moved = I.moveRange({ start: 1, end: 3 }, -5, { pixelsPerSecond: 48, targets: [], bounds });
  near(moved.start, 0, 'clamped to 0');
  // Trim the end edge.
  let trimmed = I.resizeRange({ start: 1, end: 3 }, -10, 'end', { pixelsPerSecond: 48, targets: [], bounds });
  near(trimmed.end - trimmed.start, 1 / 60, 'a clip keeps at least one frame');
  trimmed = I.resizeRange({ start: 1, end: 3 }, 40, 'end', { pixelsPerSecond: 48, targets: [], bounds });
  near(trimmed.end, 10, 'at most to the MV end');
  trimmed = I.resizeRange({ start: 1, end: 3 }, .5, 'end', { pixelsPerSecond: 48, targets: [3.52], bounds });
  near(trimmed.end, 3.5166666666666666, 'the edge snaps to a cut, then to its frame');
  near(I.nudgeRange({ start: 1, end: 3 }, 10, { bounds }).start, 1 + 10 / 60, 'Shift nudge: ten frames');
  near(I.nudgeRange({ start: 0, end: 2 }, -1, { bounds }).start, 0, 'nudges stay inside the MV');
}

class FakeElement {
  constructor() { this.listeners = {}; this.classes = new Set(); this.captured = null; }
  addEventListener(type, listener, capture) { (this.listeners[type] ||= []).push({ listener, capture: !!capture }); }
  removeEventListener(type, listener) { this.listeners[type] = (this.listeners[type] || []).filter((item) => item.listener !== listener); }
  dispatch(type, init = {}) {
    const event = { type, button: 0, isPrimary: true, pointerId: 1, pointerType: 'mouse', altKey: false, shiftKey: false,
      ctrlKey: false, metaKey: false, defaultPrevented: false, stopped: false, ...init,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, stopImmediatePropagation() { this.stopped = true; } };
    for (const { listener } of [...(this.listeners[type] || [])].sort((a, b) => b.capture - a.capture)) {
      listener(event);
      if (event.stopped && type === 'click') break;
    }
    return event;
  }
  getBoundingClientRect() { return { left: 100, right: 220, width: 120, top: 0, bottom: 20 }; }
  setPointerCapture(id) { this.captured = id; }
  get classList() { return { add: (name) => this.classes.add(name), remove: (name) => this.classes.delete(name) }; }
}

function dragging() {
  // A clip from 1 s to 3 s at 60 px/s drawn at x 100..220.
  let range = { start: 1, end: 3 }, rules = { move: true, resize: true };
  const calls = [];
  const element = new FakeElement();
  const detach = I.attachDrag(element, {
    getRange: () => ({ ...range }), pixelsPerSecond: () => 60, snapTargets: () => [4.5],
    bounds: () => ({ min: 0, max: 10 }), allowed: () => rules,
    setRange: (next, info) => { calls.push({ ...info, start: next.start, end: next.end }); if (info.phase === 'commit') range = next; },
  });
  let clicks = 0;
  element.addEventListener('click', () => { clicks++; });

  // A click without movement is a click.
  element.dispatch('pointerdown', { clientX: 150 });
  element.dispatch('pointermove', { clientX: 152 });
  element.dispatch('pointerup', { clientX: 152 });
  element.dispatch('click');
  assert.equal(calls.length, 0);
  assert.equal(clicks, 1);

  // Move by 60 px: previews per frame, exactly one commit, the click is swallowed.
  element.dispatch('pointerdown', { clientX: 150 });
  element.dispatch('pointermove', { clientX: 180 });
  element.dispatch('pointermove', { clientX: 210 });
  flush();
  element.dispatch('pointerup', { clientX: 210 });
  element.dispatch('click');
  assert.equal(clicks, 1, 'the click after a drag does not select again');
  assert.deepEqual(calls.map((call) => call.phase), ['preview', 'commit']);
  near(range.start, 2, 'moved one second');
  assert.equal(element.classes.has('mv-dragging'), false);

  // The end edge snaps to the target near it (4.5 s is 0.5 s = 30 px away from 4 s: too far; 4.45 s is close).
  calls.length = 0;
  element.dispatch('pointerdown', { clientX: 150 });
  element.dispatch('pointermove', { clientX: 177 });
  element.dispatch('pointerup', { clientX: 177 });
  near(range.end, 4.5, 'the end edge snapped to the target');
  near(range.start, 2.5, 'and the length is kept');

  // Escape cancels: the last call is a cancel with the original range, nothing committed.
  calls.length = 0;
  element.dispatch('pointerdown', { clientX: 150 });
  element.dispatch('pointermove', { clientX: 200 });
  for (const listener of listeners.keydown || []) listener({ key: 'Escape', preventDefault() {}, stopPropagation() {} });
  element.dispatch('pointerup', { clientX: 200 });
  assert.deepEqual(calls.map((call) => call.phase), ['cancel']);
  near(range.start, 2.5, 'cancelled');

  // Right edge (inside 6 px): resize. With resize blocked, the same press moves the clip.
  calls.length = 0;
  element.dispatch('pointerdown', { clientX: 217 });
  element.dispatch('pointermove', { clientX: 247 });
  element.dispatch('pointerup', { clientX: 247 });
  assert.equal(calls.at(-1).mode, 'end');
  near(range.end - range.start, 2.5, 'trimmed by half a second');
  rules = { move: true, resize: false, reason: 'locked' };
  element.dispatch('pointerdown', { clientX: 217 });
  element.dispatch('pointermove', { clientX: 247 });
  element.dispatch('pointerup', { clientX: 247 });
  assert.equal(calls.at(-1).mode, 'move', 'clipConstraints resize:false blocks the trim');
  rules = { move: false, resize: false };
  const before = calls.length;
  element.dispatch('pointerdown', { clientX: 150 });
  element.dispatch('pointermove', { clientX: 250 });
  element.dispatch('pointerup', { clientX: 250 });
  assert.equal(calls.length, before, 'a blocked clip does not move');

  // Alt drag: frame grid only (no target snap).
  rules = { move: true, resize: true };
  range = { start: 1, end: 3 };
  element.dispatch('pointerdown', { clientX: 150 });
  element.dispatch('pointermove', { clientX: 240, altKey: true });
  element.dispatch('pointerup', { clientX: 240, altKey: true });
  near(range.start, 2.5, 'Alt: 90 px = 1.5 s, no snap to 4.5');

  // Alt+→ moves one frame, Alt+Shift+← ten frames back: one commit per key.
  calls.length = 0;
  element.dispatch('keydown', { key: 'ArrowRight', altKey: true });
  element.dispatch('keydown', { key: 'ArrowLeft', altKey: true, shiftKey: true });
  assert.deepEqual(calls.map((call) => call.phase), ['commit', 'commit']);
  near(range.start, 2.5 - 9 / 60, 'nudged');
  element.dispatch('keydown', { key: 'ArrowRight' });
  assert.equal(calls.length, 2, 'a plain arrow is not a nudge');
  // A refused nudge is still owned: Alt+← must not fall through to the browser's Back.
  rules = { move: false, resize: false, reason: 'locked' };
  const refused = element.dispatch('keydown', { key: 'ArrowLeft', altKey: true });
  assert(refused.defaultPrevented, 'Alt+← on a locked clip is not the browser Back');
  assert.equal(calls.length, 2, 'and the locked clip does not move');
  rules = { move: true, resize: true };
  assert.equal(element.dispatch('keydown', { key: 'ArrowLeft', altKey: true, ctrlKey: true }).defaultPrevented, false,
    'other Alt combinations are left alone');
  detach();
  element.dispatch('keydown', { key: 'ArrowRight', altKey: true });
  assert.equal(calls.length, 2, 'detached');
}

function fixture() {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'mv_studio_tracks_12035.json'), 'utf8'));
  return data.tracks;
}

function extrapolation12035() {
  const passing = [], failing = [];
  for (const track of fixture()) {
    if (!track.events.length) continue;
    (I.extrapolationGate(track) ? passing : failing).push(track);
  }
  // Every gated track: the port reproduces every stored value.
  for (const track of passing) {
    const times = I.extrapolationTimes(track.events.map((event) => ({ id: event.id, start: event.start, duration: event.duration,
      postMode: event.values.postExtrapolationMode })));
    for (const event of track.events) {
      const computed = times.get(event.id);
      for (const [key, value] of [['preExtrapolationTime', computed.pre], ['postExtrapolationTime', computed.post]]) {
        const stored = I.storedTime(event.values[key]);
        assert(stored === value || Math.abs(stored - value) <= 1e-6, `${track.label} ${event.id} ${key}`);
      }
    }
    assert.deepEqual(I.extrapolationChanges(track, new Map()), [], `${track.label}: nothing to rewrite before an edit`);
  }
  assert.deepEqual(passing.map((track) => `${track.nativeClass} ${track.label}`), [
    'AnimationTrack CameraMotion/Camera1', 'AnimationTrack MemberMotion/Member1',
    'AnimationTrack StageEffect/Expert/Animation/litB_All', 'AnimationTrack StageEffect/Expert/Animation/litC_All',
    'AnimationTrack StageEffect/Expert/OverlayEffect/Effect_root', 'AnimationTrack StageEffect/Expert/Control/fx_stg_so2035_02_root']);
  // The custom playables keep 0/0 (no extrapolation support in the client): never recomputed.
  assert.equal(failing.length, 36);
  assert(failing.every((track) => track.nativeClass !== 'AnimationTrack'));
  assert(failing.every((track) => track.events.every((event) => event.values.preExtrapolationTime === 0 && event.values.postExtrapolationTime === 0)));
}

function holdGap() {
  // Camera-like: Hold shots one frame apart; the second shot is dragged back next to the first.
  const frame = 1 / 60;
  const track = { id: 'camera', events: [
    { id: 'a', start: 0, duration: 2, values: { preExtrapolationMode: 1, postExtrapolationMode: 1, preExtrapolationTime: 0, postExtrapolationTime: 1 } },
    { id: 'b', start: 3, duration: 2, values: { preExtrapolationMode: 1, postExtrapolationMode: 1, preExtrapolationTime: 0, postExtrapolationTime: null } },
  ] };
  assert(I.extrapolationGate(track), 'Hold before the gap: b pre is 0, a post is the gap');
  const moved = I.extrapolationChanges(track, new Map([['b', { start: 2 + frame, duration: 2 }]]));
  assert.deepEqual(moved.map((change) => [change.event.id, change.key]), [['a', 'postExtrapolationTime']]);
  near(moved[0].value, frame, 'a holds one frame up to the cut');
  // Swap the order: a becomes the last shot, its post is +∞ and is written as 3600.
  const swapped = I.extrapolationChanges(track, new Map([['a', { start: 6, duration: 2 }]]));
  const values = Object.fromEntries(swapped.map((change) => [`${change.event.id}.${change.key}`, change.value]));
  assert.equal(values['a.postExtrapolationTime'], 3600, '+∞ is written as 3600');
  near(values['b.postExtrapolationTime'], 1, 'b now holds until a');
  near(values['b.preExtrapolationTime'], 3, 'b is the first clip: pre = its start');
  assert.equal(values['a.preExtrapolationTime'], undefined, 'b holds (mode 1), so a has no pre time');
  // With None after the previous clip, the gap becomes the next clip's pre time.
  const none = { id: 'x', events: track.events.map((event) => ({ ...event, values: { ...event.values, postExtrapolationMode: 0, postExtrapolationTime: event.id === 'a' ? 1 : null, preExtrapolationTime: event.id === 'b' ? 1 : 0 } })) };
  assert(I.extrapolationGate(none));
  assert.equal(I.storedTime(3600), Infinity);
  assert.equal(I.storedTime(null), Infinity);
}

// The Unity editor's overlap blends (ComputeBlendsFromOverlaps).
function blends() {
  const clip = (id, start, duration, blendIn = -1, blendOut = -1) => ({ id, start, duration, values: { blendIn, blendOut } });
  const times = (events) => Object.fromEntries([...I.blendTimes(events)].map(([id, value]) => [id, [value.blendIn, value.blendOut]]));
  // An overlap of 0.5 s blends both clips; a gap and a touching edge do not.
  assert.deepEqual(times([clip('a', 0, 2), clip('b', 1.5, 2), clip('c', 4, 1), clip('d', 5, 1)]),
    { a: [-1, .5], b: [.5, -1], c: [-1, -1], d: [-1, -1] });
  // Equal starts: the shorter clip comes first (so0120's DoF and 11054's coloring keep this order).
  assert.deepEqual(times([clip('long', 0, 4), clip('short', 0, 3.5)]), { short: [-1, 3.5], long: [3.5, -1] });
  // Start order, not list order; an overlap of float noise is 0; a clip inside the previous one does not blend.
  assert.deepEqual(times([clip('b', 1, 1), clip('a', 0, 1 + 1e-13)]), { a: [-1, 0], b: [0, -1] });
  assert.deepEqual(times([clip('outer', 0, 4), clip('inner', 1, 1)]), { outer: [-1, -1], inner: [-1, -1] });

  // Gate: every stored value reproduced.
  const lips = { id: 'lips', events: [clip('a', 0, 2, -1, .5), clip('b', 1.5, 2, .5, -1), clip('c', 4, 1)] };
  assert(I.blendGate(lips));
  assert.deepEqual(I.blendChanges(lips, new Map()), [], 'nothing to rewrite before an edit');
  // A track the editor never blended (Activation, CustomControl, Culler: 0/0) fails the gate.
  assert.equal(I.blendGate({ id: 'act', events: [clip('a', 0, 1, 0, 0), clip('b', 2, 1, 0, 0)] }), false);
  assert.equal(I.blendGate({ id: 'stale', events: [clip('a', 0, 2, -1, .4), clip('b', 1.5, 2, .4, -1)] }), false, 'a stale blend fails');
  assert.equal(I.blendGate({ id: 'none', events: [{ id: 'a', start: 0, duration: 1, values: {} }] }), false, 'no stored blends');
  assert.equal(I.blendGate({ id: 'empty', events: [] }), false);

  // Moving b later shrinks the overlap; moving it to a's end clears both blends; a trim of a shrinks it too.
  const write = (changes) => Object.fromEntries(changes.map((change) => [`${change.event.id}.${change.key}`, change.value]));
  assert.deepEqual(write(I.blendChanges(lips, new Map([['b', { start: 1.75 }]]))), { 'a.blendOut': .25, 'b.blendIn': .25 });
  assert.deepEqual(write(I.blendChanges(lips, new Map([['b', { start: 2 }]]))), { 'a.blendOut': -1, 'b.blendIn': -1 }, 'touching edges do not blend');
  assert.deepEqual(write(I.blendChanges(lips, new Map([['a', { duration: 1.75 }]]))), { 'a.blendOut': .25, 'b.blendIn': .25 });
  // c dragged onto b: b blends out into c, and c blends in.
  assert.deepEqual(write(I.blendChanges(lips, new Map([['c', { start: 3 }]]))), { 'b.blendOut': .5, 'c.blendIn': .5 });
}

// Real timelines (optional): MV_STUDIO_TRACKS_JSON is the per-MV parse_timeline track dump
// ({ label: tracks }) of the 13 stock timelines the editing census used. Without it, skipped.
function blendsOnStockTimelines() {
  const file = process.env.MV_STUDIO_TRACKS_JSON;
  if (!file || !fs.existsSync(file)) return 'skipped (no MV_STUDIO_TRACKS_JSON)';
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  let gated = 0, ungated = 0;
  const ungatedClasses = new Set();
  for (const tracks of Object.values(data)) {
    for (const track of tracks) {
      if (!track.events.length || !('blendIn' in track.events[0].values)) continue;
      if (I.blendGate(track)) {
        gated++;
        assert.deepEqual(I.blendChanges(track, new Map()), [], track.label);
      } else {
        ungated++;
        ungatedClasses.add(track.nativeClass);
        // Never blended by the editor: 0/0 on every clip.
        assert(track.events.every((event) => event.values.blendIn === 0 && event.values.blendOut === 0), track.label);
      }
    }
  }
  assert.deepEqual({ gated, ungated }, { gated: 621, ungated: 152 });
  assert.deepEqual([...ungatedClasses].sort(), ['ActivationTrack', 'CustomControlTrack', 'LiveMemberCullerTrack']);
  return `${gated} tracks gated, ${ungated} never blended`;
}

// Timing fields per clip type (Unity ClipCaps).
function clipCaps() {
  const field = (track, playableClass, key) => I.timingField(I.clipCaps(track, { values: { playableClass } }), key);
  const timing = ['preExtrapolationMode', 'postExtrapolationMode', 'preExtrapolationTime', 'postExtrapolationTime', 'clipIn',
    'timeScale', 'easeIn', 'easeOut', 'blendIn', 'blendOut'];
  const open = (track, playableClass) => timing.filter((key) => field(track, playableClass, key));
  const lane = { kind: 'dance' }, camera = { kind: 'camera' }, lights = { kind: 'lighting' };
  assert.equal(I.clipCaps(lane, { values: {} }), null, 'no playable class: nothing restricted');
  assert.deepEqual(open(lane, 'AnimationPlayableAsset'), timing, 'Animation clips: every field (ClipCaps.All)');
  assert.deepEqual(open(lights, 'LiveColoringClip'), ['easeIn', 'easeOut', 'blendIn', 'blendOut'], 'game clips: blending only');
  assert.deepEqual(open(lane, 'ActivationPlayableAsset'), [], 'ClipCaps.None');
  assert.deepEqual(open({ kind: 'effects' }, 'CustomControlClip'), ['clipIn']);
  assert.deepEqual(open(lane, 'LiveMemberCullerClip'), []);
  assert.deepEqual(open(lane, 'ControlPlayableAsset'), ['clipIn', 'timeScale']);
  // Camera shots: modes, not offset or speed. Every mode once the preview plays them
  // (MVStudioScene.cameraLocalTime), None and Hold before that.
  assert.deepEqual(open(camera, 'AnimationPlayableAsset'), timing.filter((key) => key !== 'clipIn' && key !== 'timeScale'));
  const shot = { values: { playableClass: 'AnimationPlayableAsset' } }, scene = globalThis.MVStudioScene;
  try {
    delete globalThis.MVStudioScene;
    assert.deepEqual(I.clipCaps(camera, shot).modes, [0, 1], 'a preview without cameraLocalTime: None and Hold');
    globalThis.MVStudioScene = { create() {} };
    assert.deepEqual(I.clipCaps(camera, shot).modes, [0, 1]);
    globalThis.MVStudioScene = { create() {}, cameraLocalTime() { return 0; } };
    assert.deepEqual(I.clipCaps(camera, shot).modes, [0, 1, 2, 3, 4], 'the preview plays every mode: all five');
    assert.deepEqual(open(camera, 'AnimationPlayableAsset'), timing.filter((key) => key !== 'clipIn' && key !== 'timeScale'),
      'offset and speed stay read only');
  } finally {
    if (scene === undefined) delete globalThis.MVStudioScene;
    else globalThis.MVStudioScene = scene;
  }
  assert.deepEqual(I.clipCaps(lane, { values: { playableClass: 'AnimationPlayableAsset' } }).modes, [0, 1, 2, 3, 4]);
  assert.deepEqual(I.clipCaps(camera, { values: { playableClass: 'LiveCameraOffsetClip' } }).modes, [], 'a camera offset clip is a game clip');
  assert.equal(I.timingField(I.clipCaps(lights, { values: { playableClass: 'LiveColoringClip' } }), 'color'), true, 'other keys are not timing');
}

// Stock timelines (optional, as above): a read-only timing field never hides a stored value.
function capsOnStockTimelines() {
  const file = process.env.MV_STUDIO_TRACKS_JSON;
  if (!file || !fs.existsSync(file)) return 'skipped';
  const defaults = { preExtrapolationMode: 0, postExtrapolationMode: 0, preExtrapolationTime: 0, postExtrapolationTime: 0,
    clipIn: 0, timeScale: 1, easeIn: 0, easeOut: 0 };
  let clips = 0, locked = 0;
  for (const tracks of Object.values(JSON.parse(fs.readFileSync(file, 'utf8')))) {
    for (const track of tracks) {
      for (const event of track.events) {
        const caps = I.clipCaps(track, event);
        if (!caps) continue;
        clips++;
        for (const [key, value] of Object.entries(event.values)) {
          if (I.timingField(caps, key)) continue;
          locked++;
          // Blends of a clip without Blending: 0/0 (never computed).
          const expected = key === 'blendIn' || key === 'blendOut' ? 0 : defaults[key];
          assert.equal(value, expected, `${track.label} ${event.id} ${key}`);
        }
        if (caps.camera) assert(caps.modes.includes(event.values.preExtrapolationMode) && caps.modes.includes(event.values.postExtrapolationMode));
      }
    }
  }
  return `${locked} read-only fields on ${clips} clips hold their defaults`;
}

snapping();
dragging();
extrapolation12035();
holdGap();
blends();
clipCaps();
const stock = [blendsOnStockTimelines(), capsOnStockTimelines()].join('; ');
console.log('MV Studio clip interaction: snaps (frame, targets, Alt), clamps, one commit per drag, Escape, blocked resize, nudges, extrapolation port on 12035, overlap blends, timing fields per clip type; stock timelines: ' + stock + '.');
