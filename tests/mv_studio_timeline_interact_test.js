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

snapping();
dragging();
extrapolation12035();
holdGap();
console.log('MV Studio clip interaction: snaps (frame, targets, Alt), clamps, one commit per drag, Escape, blocked resize, nudges, extrapolation port on 12035.');
