/* MV import progress (mv-studio-import-progress.js): weights from the server plan,
   member phases, a monotonic percentage that reaches 100 only when the page has
   loaded the scene, labels for every step, and the indeterminate mode of an older
   server that sends no plan. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-import-progress.js');
const Progress = globalThis.MVStudioImportProgress;

const plan = {
  type: 'plan', v: 1, members: 2, bytes: 4 * 1024 * 1024, t: 0.2, read: 0,
  steps: [{ id: 'resolve', w: 3 }, { id: 'timeline', w: 20 }, { id: 'stage', w: 12 }, { id: 'effect', w: 16 },
    { id: 'member', index: 1, of: 2, w: 35 }, { id: 'member', index: 2, of: 2, w: 35 }, { id: 'audio', w: 5 },
    { id: 'finish', w: 2 }],
};
const state = (step, value, extra = {}) => ({ type: 'progress', step, state: value, ...extra });

{
  const tracker = Progress.create(1000);
  const percents = [];
  const see = (now) => { const view = tracker.snapshot(now); percents.push(view.percent); return view; };
  let view = see(1000);
  assert.equal(view.determinate, false, 'no plan yet');
  assert.deepEqual(view.step, ['Preparing MV from game…', {}]);
  assert.equal(tracker.record(plan), true);
  assert.equal(tracker.record({ type: 'stage' }), false);
  tracker.record(state('resolve', 'done'));
  view = see(1500);
  assert.equal(view.determinate, true);
  assert.equal(view.percent, Math.floor(90 * 3 / 128));
  assert.deepEqual(view.members, [0, 2]);
  tracker.record(state('timeline', 'start', { read: 1024 * 1024 }));
  view = see(2000);
  assert.deepEqual(view.step, [Progress.STEP_LABELS.timeline, { index: '', count: 2, name: '' }]);
  assert.deepEqual(view.bytes, [1024 * 1024, 4 * 1024 * 1024]);
  // The timeline parse reports its bundle, tracks and effect readers.
  const atStart = see(2010).percent;
  tracker.record({ type: 'progress', step: 'timeline', phase: 'bundle' });
  assert.deepEqual(see(2020).phase, [Progress.PHASE_LABELS.bundle, { done: '', total: '' }]);
  tracker.record({ type: 'progress', step: 'timeline', phase: 'tracks' });
  const afterTracks = see(2030).percent;
  assert.equal(afterTracks, Math.floor(90 * (3 + 20 * 0.45) / 128));
  tracker.record({ type: 'progress', step: 'timeline', phase: 'effects', done: 12, total: 23 });
  view = see(2040);
  assert.deepEqual(view.phase, [Progress.PHASE_LABELS.effects, { done: 12, total: 23 }]);
  assert(atStart < afterTracks && afterTracks < view.percent, [atStart, afterTracks, view.percent].join(','));
  tracker.record(state('timeline', 'done'));
  tracker.record(state('stage', 'start'));
  tracker.record({ type: 'progress', step: 'stage', phase: 'textures', done: 30 });
  const midStage = see(2500).percent;
  tracker.record(state('stage', 'cached'));
  view = see(2600);
  assert.equal(view.cached, true);
  assert(view.percent > midStage);
  tracker.record(state('effect', 'skipped'));
  tracker.stage();
  tracker.record(state('member', 'start', { index: 1, of: 2, name: '上原歩夢' }));
  tracker.record({ type: 'progress', step: 'member', index: 1, of: 2, phase: 'motion' });
  view = see(3000);
  assert.deepEqual(view.step, [Progress.STEP_LABELS.member, { index: 1, count: 2, name: '上原歩夢' }]);
  assert.deepEqual(view.phase, [Progress.PHASE_LABELS.motion, { done: '', total: '' }]);
  tracker.record({ type: 'progress', step: 'member', index: 1, of: 2, phase: 'textures', done: 12 });
  assert.deepEqual(see(3100).phase, [Progress.PHASE_LABELS.textures, { done: 12, total: '' }]);
  tracker.record({ type: 'progress', step: 'member', index: 1, of: 2, phase: 'animation', done: 40, total: 100 });
  assert.deepEqual(see(3200).phase, [Progress.PHASE_LABELS.animation, { done: 40, total: 100 }]);
  // A late or repeated tick never moves the bar back.
  tracker.record({ type: 'progress', step: 'member', index: 1, of: 2, phase: 'textures', done: 1 });
  see(3300);
  tracker.record(state('member', 'done', { index: 1, of: 2 }));
  assert.deepEqual(see(3400).members, [1, 2]);
  tracker.record(state('member', 'start', { index: 2, of: 2, name: 'Kasumi' }));
  tracker.record(state('member', 'failed', { index: 2, of: 2 }));
  tracker.record(state('audio', 'start'));
  tracker.record(state('audio', 'done'));
  tracker.record(state('finish', 'start'));
  tracker.record(state('finish', 'done'));
  view = see(4000);
  assert.equal(view.percent, 90, 'the server part is 90%');
  tracker.complete();
  view = see(4100);
  assert.deepEqual(view.step, ['Loading 3D models…', {}], 'no 0/0 before the scene counts its models');
  tracker.page({ done: 1, total: 4 });
  assert.deepEqual(see(4150).step, ['Loading 3D models {done}/{total}…', { done: 1, total: 4 }]);
  tracker.page({ done: 4, total: 4 });
  assert.equal(see(4200).percent, 97);
  tracker.page({ phase: 'effects' });
  view = see(4300);
  assert.deepEqual(view.step, ['Preparing effects…', {}]);
  tracker.page({ phase: 'ready' });
  view = see(4400);
  assert.equal(view.percent, 100);
  assert.deepEqual(view.step, ['Ready to play', {}]);
  for (let index = 1; index < percents.length; index++) assert(percents[index] >= percents[index - 1], percents.join(','));
  assert.equal(view.elapsed, 3.4);
}

{
  // An older server: no plan, no progress. The bar is indeterminate until the
  // project arrives, then follows the page's own loading.
  const tracker = Progress.create(0);
  tracker.stage();
  let view = tracker.snapshot(61000);
  assert.equal(view.determinate, false);
  assert.deepEqual(view.step, ['Stage is ready. Members are still loading.', {}]);
  assert.equal(view.members, null);
  assert.equal(view.bytes, null);
  assert.equal(Progress.formatElapsed(view.elapsed), '1:01');
  tracker.complete();
  tracker.page({ done: 1, total: 2 });
  view = tracker.snapshot(62000);
  assert.equal(view.determinate, true);
  assert.equal(view.percent, 35);
  assert.equal(tracker.record({ type: 'plan', steps: [] }), false, 'an empty plan is ignored');
}

assert.equal(Progress.megabytes(7.78 * 1024 * 1024), '7.8');

// Every label the tracker can show has Korean and Japanese text.
const i18n = fs.readFileSync(path.join(__dirname, '..', 'webtools', 'i18n.py'), 'utf8');
const labels = [...Object.values(Progress.STEP_LABELS), ...Object.values(Progress.PHASE_LABELS), 'Preparing MV from game…',
  'Stage is ready. Members are still loading.', 'Loading 3D models {done}/{total}…', 'Loading 3D models…',
  'Ready to play', 'Preparing effects…',
  'Reused from cache', 'Members done {done}/{count}', 'Game data {read}/{total} MB', 'Cancel import', 'Cancelling…',
  'MV import cancelled.'];
for (const label of labels) {
  const row = new RegExp('^\\s*' + JSON.stringify(label).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ': \\("[^"]+", "[^"]+"\\)', 'm');
  assert.match(i18n, row, label);
}
console.log('PASS: MV import progress weights, phases, monotonic percent, page share, old-server mode and labels');
