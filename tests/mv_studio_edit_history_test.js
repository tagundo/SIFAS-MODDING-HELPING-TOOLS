/* MV Studio edit history (mv-studio-edit-history.js): apply/undo/redo, gestures and
   coalescing, the 200-entry limit, originals captured once before the first change,
   "edited" against those originals, insert/remove, and inert entries once the
   project they targeted is gone. */
'use strict';
const assert = require('node:assert/strict');

globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-edit-history.js');
const { create, stable, editedView } = globalThis.MVStudioEditHistory;

const sample = () => ({
  version: 1, duration: 20,
  tracks: [
    { id: 'camera', kind: 'camera', events: [
      { id: 'shot-1', label: 'Shot 1', start: 0, duration: 4, values: { fov: 30, color: { r: 1, g: 1, b: 1, a: 1 } }, editableValues: ['fov', 'color'] },
      { id: 'shot-2', label: 'Shot 2', start: 4, duration: 4, values: { fov: 40 }, editableValues: ['fov'] }] },
    { id: 'mouth', kind: 'mouth', events: [{ id: 'lip-1', start: 1, duration: 1, values: { weight: .5 } }] },
  ],
  performers: [{ id: 'member-1', position: 1, transform: { position: [0, 0, 0] } }],
  soundtrack: { url: '/api/x', offset: 0 },
  quality: { mode: 1, values: { shadow: true } },
});

const setValue = (event, key, after, label = 'Edit value') => ({ label, changes: [{ target: { kind: 'event', track: 'camera', event }, path: ['values', key], after }] });

function basics() {
  let project = sample();
  const input = JSON.parse(JSON.stringify(project));
  const events = [];
  const history = create({ getProject: () => project, onChange: (change) => events.push(change) });
  assert.equal(history.canUndo(), false);
  assert.equal(history.apply(setValue('shot-1', 'fov', 30)), false, 'a command that changes nothing is not recorded');
  assert.equal(project.editor, undefined, 'no editor layer before the first real change');
  assert.deepEqual(project, input);

  const version = history.version;
  assert.equal(history.apply(setValue('shot-1', 'fov', 55)), true);
  assert(history.version > version, 'version moves on every change');
  assert.equal(project.tracks[0].events[0].values.fov, 55);
  assert.deepEqual(project.editor, { version: 1, originals: { 'shot-1': input.tracks[0].events[0] } },
    'the event is copied before its first change');
  assert.equal(events.length, 1);
  assert.equal(events[0].direction, 'do');
  assert.deepEqual(events[0].changes, [{ target: { kind: 'event', track: 'camera', event: 'shot-1' }, path: ['values', 'fov'], op: 'set', before: 30, after: 55 }]);
  events[0].command.changes[0].before = 999;   // listeners get copies
  assert.equal(events[0].command.label, 'Edit value');
  assert.equal(history.peekUndo().label, 'Edit value');
  assert.deepEqual([...history.editedEvents()], ['shot-1']);

  // A second change keeps the first original.
  history.apply(setValue('shot-1', 'fov', 60));
  assert.equal(project.editor.originals['shot-1'].values.fov, 30);

  assert.equal(history.undo(), true);
  assert.equal(project.tracks[0].events[0].values.fov, 55);
  assert.equal(events.at(-1).direction, 'undo');
  assert.equal(history.undo(), true);
  assert.equal(project.tracks[0].events[0].values.fov, 30, 'a listener editing its copy does not change undo');
  assert.equal(history.undo(), false, 'nothing left to undo');
  assert.deepEqual([...history.editedEvents()], [], 'back to the original values: not edited');
  assert.equal(history.redo(), true);
  assert.equal(events.at(-1).direction, 'redo');
  assert.equal(project.tracks[0].events[0].values.fov, 55);
  assert.equal(history.canRedo(), true);
  history.apply(setValue('shot-2', 'fov', 41));
  assert.equal(history.canRedo(), false, 'a new command clears redo');

  // A manual edit back to the original value is not "edited" either.
  history.apply(setValue('shot-1', 'fov', 30));
  assert.equal(history.editedEvents().has('shot-1'), false);
  assert.equal(history.editedEvents().has('shot-2'), true);

  // Values are cloned on the way in.
  const color = { r: 2, g: 1, b: .5, a: 1 };
  history.apply(setValue('shot-1', 'color', color));
  color.r = 9;
  assert.equal(project.tracks[0].events[0].values.color.r, 2);
}

function gestures() {
  const project = sample();
  const history = create({ getProject: () => project });
  history.begin('Drag colour');
  history.begin();
  for (const value of [.1, .2, .3]) history.apply(setValue('shot-1', 'fov', value));
  history.end();
  history.apply(setValue('shot-2', 'fov', 99));
  history.end();
  assert.deepEqual(history.size(), { undo: 1, redo: 0 }, 'one gesture, one entry (nested depth counted)');
  assert.equal(history.peekUndo().label, 'Drag colour');
  history.undo();
  assert.equal(project.tracks[0].events[0].values.fov, 30);
  assert.equal(project.tracks[0].events[1].values.fov, 40);
  history.redo();
  assert.equal(project.tracks[0].events[0].values.fov, .3);
  assert.equal(project.tracks[0].events[1].values.fov, 99);

  // Coalesce key outside a gesture: consecutive commands merge until something else happens.
  history.apply({ ...setValue('shot-1', 'fov', 1), coalesce: 'nudge' });
  history.apply({ ...setValue('shot-1', 'fov', 2), coalesce: 'nudge' });
  assert.deepEqual(history.size(), { undo: 2, redo: 0 });
  history.apply(setValue('shot-2', 'fov', 5));
  history.apply({ ...setValue('shot-1', 'fov', 3), coalesce: 'nudge' });
  assert.deepEqual(history.size(), { undo: 4, redo: 0 });
  history.undo(); history.undo(); history.undo();
  assert.equal(project.tracks[0].events[0].values.fov, .3);

  // Tokens: nested begins share one; a stale token's end() leaves a newer gesture open.
  assert.equal(history.gestureToken, null);
  const first = history.begin('Leaked');
  assert.equal(typeof first, 'object', 'a token is an object begin() made');
  assert.equal(history.gestureToken, first);
  assert.equal(history.begin(), first, 'a nested begin returns the open gesture\'s token');
  history.apply(setValue('shot-1', 'fov', 7));
  while (history.gestureActive) history.end();   // the host closes a gesture left open
  const second = history.begin('Next');
  assert.notEqual(second, first);
  history.end(first);
  assert.equal(history.gestureActive, true, 'a late end() of the closed gesture is ignored');
  history.apply(setValue('shot-1', 'fov', 8));
  history.end(second);
  assert.equal(history.gestureActive, false);
  history.apply(setValue('shot-2', 'fov', 9));
  assert.deepEqual([history.size().undo, history.peekUndo().label], [4, 'Edit value'], 'Leaked, Next, then a command of its own');
  history.undo();
  assert.equal(history.peekUndo().label, 'Next');
  const stale = history.begin('Dropped by undo');
  history.undo();
  assert.equal(history.gestureActive, false, 'undo closes an open gesture');
  history.end(stale);
  assert.equal(history.gestureActive, false);

  // end() with anything that is not a token ends the open gesture: history.end can be
  // given straight to addEventListener('change', …), which passes it the Event.
  for (const notToken of [{ type: 'change', target: {} }, 1, 'x', null, () => {}]) {
    history.begin('Listener');
    history.end(notToken);
    assert.equal(history.gestureActive, false, 'end(' + typeof notToken + ') is a plain end()');
  }
  // A token of another history is a token, just not this gesture's.
  const other = create({ getProject: () => project });
  const foreign = other.begin('Elsewhere');
  history.begin('Here');
  history.end(foreign);
  assert.equal(history.gestureActive, true, 'another history\'s token does not end this gesture');
  history.end();
  other.end(foreign);
  assert.equal(other.gestureActive, false);
  assert.equal(history.gestureToken, null);

  // onBegin runs when a gesture opens (not for a nested begin), with begin()'s settings.
  const opened = [];
  const hooked = create({ getProject: () => project, onBegin: (token, settings) => opened.push([token, settings]) });
  const owner = { contains: () => true };
  const outer = hooked.begin('Hooked', { owner });
  hooked.begin('Nested', { owner: null });
  hooked.end(); hooked.end();
  hooked.begin('Plain');
  hooked.end();
  assert.equal(opened.length, 2);
  assert.equal(opened[0][0], outer);
  assert.equal(opened[0][1].owner, owner);
  assert.deepEqual(opened[1][1], {}, 'no settings: an empty object');
  const broken = create({ getProject: () => project, onBegin: () => { throw new Error('hook'); } });
  const error = console.error;
  console.error = () => {};
  try { assert.equal(typeof broken.begin('Survives'), 'object'); } finally { console.error = error; }
  assert.equal(broken.gestureActive, true, 'a throwing hook leaves the gesture consistent');
  broken.end();
  assert.equal(broken.gestureActive, false);
}

function limit() {
  const project = sample();
  const history = create({ getProject: () => project, limit: 200 });
  for (let index = 1; index <= 205; index++) history.apply(setValue('shot-1', 'fov', index));
  assert.deepEqual(history.size(), { undo: 200, redo: 0 });
  while (history.undo());
  assert.equal(project.tracks[0].events[0].values.fov, 5, 'the five oldest entries were dropped');
}

function structure() {
  const project = sample();
  const history = create({ getProject: () => project });
  const added = { id: 'mouth:u1', start: 3, duration: 1, values: { weight: 1 } };
  assert(history.apply({ label: 'Duplicate clip', changes: [
    { target: { kind: 'track', track: 'mouth' }, path: ['events'], op: 'insert', index: 1, value: added },
    { target: { kind: 'event', track: 'mouth', event: 'mouth:u1' }, path: ['values', 'weight'], after: .25 }] }));
  assert.deepEqual(project.tracks[1].events.map((event) => event.id), ['lip-1', 'mouth:u1']);
  assert.equal(project.tracks[1].events[1].values.weight, .25, 'a change can build on an earlier change of the same command');
  assert.equal(project.editor.originals['mouth:u1'], null, 'an added clip has no native original');
  assert(history.editedEvents().has('mouth:u1'), 'an added clip counts as edited');
  history.undo();
  assert.deepEqual(project.tracks[1].events.map((event) => event.id), ['lip-1']);
  history.redo();
  assert.equal(project.tracks[1].events[1].values.weight, .25);
  assert(history.apply({ label: 'Delete clip', changes: [{ target: { kind: 'track', track: 'mouth' }, path: ['events'], op: 'remove', index: 0 }] }));
  assert.deepEqual(project.tracks[1].events.map((event) => event.id), ['mouth:u1']);
  history.undo();
  assert.deepEqual(project.tracks[1].events.map((event) => event.id), ['lip-1', 'mouth:u1']);
  assert.equal(project.tracks[1].events[0].values.weight, .5);

  // Editor-layer records: missing containers are created and removed again on undo;
  // after: undefined deletes a key.
  const editor = (path, after) => ({ label: 'Camera key', changes: [{ target: { kind: 'editor' }, path, after }] });
  assert(history.apply(editor(['camera', 'shots', 'shot-1'], { mode: 'offset', keys: [{ frame: 0 }] })));
  assert.deepEqual(project.editor.camera, { shots: { 'shot-1': { mode: 'offset', keys: [{ frame: 0 }] } } });
  assert(history.apply(editor(['camera', 'shots', 'shot-1'], undefined)));
  assert.deepEqual(project.editor.camera.shots, {});
  history.undo();
  assert.equal(project.editor.camera.shots['shot-1'].mode, 'offset');
  history.undo();
  assert.equal(project.editor.camera, undefined, 'containers created by an undone change are removed');

  // Other targets.
  assert(history.apply({ label: 'Move performer', changes: [{ target: { kind: 'performer', id: 'member-1' }, path: ['transform', 'position'], after: [1, 0, 0] }] }));
  assert(history.apply({ label: 'Offset', changes: [{ target: { kind: 'soundtrack' }, path: ['offset'], after: .5 }] }));
  assert(history.apply({ label: 'Quality', changes: [{ target: { kind: 'quality' }, path: ['values', 'shadow'], after: false }] }));
  assert.deepEqual([project.performers[0].transform.position, project.soundtrack.offset, project.quality.values.shadow], [[1, 0, 0], .5, false]);
  history.undo(); history.undo(); history.undo();
  assert.deepEqual([project.performers[0].transform.position, project.soundtrack.offset, project.quality.values.shadow], [[0, 0, 0], 0, true]);
}

function inert() {
  let project = sample();
  const history = create({ getProject: () => project });
  history.apply(setValue('shot-1', 'fov', 70));
  // A new project without these ids: the entry cannot reach anything.
  project = { version: 1, duration: 5, tracks: [{ id: 'other', kind: 'stage', events: [{ id: 'x', start: 0, duration: 1, values: { a: 1 } }] }] };
  const before = JSON.stringify(project);
  assert.equal(history.undo(), false);
  assert.equal(JSON.stringify(project), before, 'an inert entry changes nothing');
  assert.equal(project.editor, undefined);
  assert.equal(history.apply(setValue('shot-1', 'fov', 1)), false, 'a target that does not resolve is not recorded');
  history.clear();
  assert.deepEqual(history.size(), { undo: 0, redo: 0 });
}

function views() {
  const project = sample();
  // compareView drops derived keys (the editor drops recomputed extrapolation times).
  const history = create({ getProject: () => project, compareView: (_track, event) => {
    const view = editedView(event);
    if (view && view.values) { view.values = { ...view.values }; delete view.values.derived; }
    return view;
  } });
  history.apply({ label: 'derived', changes: [{ target: { kind: 'event', track: 'camera', event: 'shot-2' }, path: ['values', 'derived'], after: 1 }] });
  assert.equal(history.editedEvents().has('shot-2'), false);
  // editableValues is not part of "edited" (a migration may update it).
  history.apply({ label: 'list', changes: [{ target: { kind: 'event', track: 'camera', event: 'shot-1' }, path: ['editableValues'], after: ['fov', 'color', 'x'] }] });
  assert.equal(history.editedEvents().has('shot-1'), false);
  assert.equal(stable({ b: 1, a: [1, { d: 2, c: 3 }] }), stable({ a: [1, { c: 3, d: 2 }], b: 1 }));

  // A caller that already wrote the value passes before: it is recorded, not re-read.
  project.tracks[0].events[0].values.fov = 12;
  assert(history.apply({ label: 'live', changes: [{ target: { kind: 'event', track: 'camera', event: 'shot-1' }, path: ['values', 'fov'], before: 30, after: 12 }] }));
  history.undo();
  assert.equal(project.tracks[0].events[0].values.fov, 30);
}

basics();
gestures();
limit();
structure();
inert();
views();
console.log('MV Studio edit history: apply/undo/redo, gestures and coalescing, limit 200, originals once, edited, insert/remove, editor containers, inert entries.');
