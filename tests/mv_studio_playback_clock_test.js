/* MV Studio playback clock (mv-studio-playback-clock.js) against simulated clocks.

   A simulated soundtrack plays at wall-clock rate (optionally drifting by ±1%) after a start
   latency, and reports its position only at coarse update moments (20-50 ms apart unless
   stated, with optional reading jitter), as browsers and phone web views do. Display frames
   arrive at 60 Hz (or 30 Hz) with optional timestamp jitter. The host feeds the clock one
   reading per frame, as mv-studio.js tick() does, and moves the soundtrack when the clock
   asks it to realign.

   Bounds checked, with the documented constants written out here (not read from DEFAULTS, so a
   change to the module's constants fails this test): once locked, every frame advances by its
   frame interval times a rate within 1 ± 3 %, never by zero and never backwards, except on the frames
   that snap forward or hold; the shown time stays within 30 ms of the soundtrack at 60 Hz
   (45 ms at 30 Hz), drift of ±1 % included: the dead zone (8 ms) plus the drift the rate
   correction carries (1 % × slewTime 0.5 s = 5 ms) plus the up to one frame by which the
   last reading trails the soundtrack. Errors beyond `snap` (50 ms) that two readings
   confirm (three for a backward one) are corrected at once: forward by snapping, backward
   by holding the picture.
   Run: node tests/mv_studio_playback_clock_test.js */
'use strict';
const assert = require('node:assert/strict');

globalThis.window = globalThis;
require('../webtools/web/static/mv-studio-playback-clock.js');
const Clock = globalThis.MVStudioPlaybackClock;
// The documented contract: rate within 1 ± 3 %, dead zone 8 ms, snap beyond 50 ms once two
// fresh readings agree, realign a soundtrack more than 0.5 s behind, give up on one not advancing
// for 1 s, stall limit at most 0.5 s, frame gaps over 250 ms resynchronise.
const SLEW = 0.03, DEAD_ZONE = 0.008, SNAP = 0.05, CONFIRM = 2, REALIGN = 0.5, GIVE_UP = 1, MAX_STALL = 0.5, MAX_GAP = 0.25;
assert.deepEqual(Clock.DEFAULTS, { deadZone: DEAD_ZONE, slewTime: 0.5, maxSlew: SLEW, filterTime: 0.2, snap: SNAP, realign: REALIGN,
  confirm: CONFIRM, stallSteps: 3, minStall: 0.1, maxStall: MAX_STALL, giveUp: GIVE_UP, maxGap: MAX_GAP }, 'the documented constants');

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// A soundtrack whose media clock is read in coarse steps. Times in ms (wall), positions in s.
// A seek takes `seekTime` (s): until then the element is seeking and reads the sought position.
function soundtrack(random, { steps = [0.02, 0.05], jitter = 0, drift = 0, latency = 0.03, seekable = true, seekTime = 0 } = {}) {
  const s = { playing: false, stalled: false, paused: true, ended: false, base: 0, anchor: 0, reported: 0, next: Infinity, seeks: 0, seekable,
    seekTime, seekingUntil: -Infinity };
  const step = () => (steps[0] + (steps[1] - steps[0]) * random()) * 1000;
  s.truth = (t) => s.playing && !s.stalled ? s.base + Math.max(0, t - s.anchor) / 1000 * (1 + drift) : s.base;
  s.play = (position, t) => {
    Object.assign(s, { base: position, anchor: t + latency * 1000, playing: true, paused: false, stalled: false, reported: position });
    s.next = t + step();
  };
  s.pause = (t) => { s.base = s.reported = s.truth(t); s.playing = false; s.paused = true; };
  s.seek = (position, t) => {
    s.seeks++;
    if (!s.seekable) return;
    s.seekingUntil = t + s.seekTime * 1000;
    Object.assign(s, { base: position, anchor: s.seekingUntil + latency * 1000, reported: position });
    s.next = s.seekingUntil + step();
  };
  s.seeking = (t) => t < s.seekingUntil;
  s.stall = (t) => { s.base = s.truth(t); s.stalled = true; };
  s.resume = (t) => { s.anchor = t; s.stalled = false; };
  // The soundtrack's position itself jumps (a skip): readings follow from the next update.
  s.jump = (by, t) => { s.base = s.truth(t) + by; s.anchor = t; };
  s.read = (t) => {
    while (s.next <= t) {
      s.reported = s.truth(s.next) + (random() * 2 - 1) * jitter;
      s.next += step();
    }
    return s.reported;
  };
  return s;
}

// Plays `seconds` of frames. `events[k](audio, clock, t, host)` runs before frame k.
// `frames(k, random)` optionally gives each frame interval (ms).
function run({ seed = 1, seconds = 5, fps = 60, frameJitter = 0, events = {}, frames = null, start = 0, audio: audioOptions = {},
  soundtrack: present = true, clockOptions = {} } = {}) {
  const random = rng(seed), audio = soundtrack(random, audioOptions), clock = Clock.create(clockOptions);
  const frame = 1000 / fps, host = { reading: null, ready: true, playing: true, loading: null };
  let t = 1000, clean = 1000;
  if (present) audio.play(start, t);
  clock.start(start, t);
  const rows = [];
  const count = Math.round(seconds * fps);
  for (let k = 1; k <= count; k++) {
    clean += frames ? frames(k, random) : frame;
    t = clean + (frames ? 0 : (random() * 2 - 1) * frameJitter);
    const event = events[k];
    if (event) event(audio, clock, t, host);
    if (!host.playing) continue;
    let reading = NaN;
    if (present && !audio.paused && !audio.ended) reading = host.reading ? host.reading(audio, t) : audio.read(t);
    const out = clock.next(t, reading, host.ready && !audio.seeking(t), host.loading ? host.loading(audio, t) : false);
    if (out.realign) audio.seek(out.time, t);
    rows.push({ k, t, time: out.time, truth: audio.truth(t), reading, mode: out.mode, holding: out.holding, rate: out.rate, realign: out.realign,
      seeking: audio.seeking(t) });
  }
  return { rows, clock, audio, state: clock.state() };
}

// Per-frame advances of `rows` (from index 1): { advance, interval, ratio }.
function steps(rows) {
  const list = [];
  for (let index = 1; index < rows.length; index++) {
    const advance = rows[index].time - rows[index - 1].time, interval = (rows[index].t - rows[index - 1].t) / 1000;
    list.push({ k: rows[index].k, advance, interval, ratio: advance / interval });
  }
  return list;
}

const after = (rows, ms) => rows.filter((row) => row.t >= rows[0].t + ms);
const offsets = (rows) => rows.map((row) => row.time - row.truth);
const maxAbs = (values) => Math.max(...values.map(Math.abs));
const monotonic = (rows, label) => {
  for (const step of steps(rows)) assert(step.advance >= 0, `${label}: frame ${step.k} goes back by ${-step.advance}`);
};
const evenSteps = (rows, label, slack = 1e-9) => {
  for (const step of steps(rows)) {
    assert(step.ratio >= 1 - SLEW - slack && step.ratio <= 1 + SLEW + slack,
      `${label}: frame ${step.k} advances ${step.advance * 1000} ms over ${step.interval * 1000} ms`);
  }
};
// The old tick(): the time is the soundtrack's reading on every frame.
const naiveZeroFrames = (rows) => steps(rows.map((row) => ({ ...row, time: row.reading }))).filter((step) => step.advance === 0).length;
const report = {};

// ---- Coarse readings at 60 Hz: even advances, bounded offset, no repeated times ----------------
{
  let naive = 0, total = 0, worst = 0;
  for (let seed = 1; seed <= 6; seed++) {
    const { rows, state } = run({ seed, seconds: 6, frameJitter: 1.5, audio: { jitter: 0.003 } });
    monotonic(rows, `coarse seed ${seed}`);
    const settled = after(rows, 1000);
    evenSteps(settled, `coarse seed ${seed}`);
    const offset = maxAbs(offsets(settled));
    assert(offset <= 0.030, `coarse seed ${seed}: shown time within 30 ms of the soundtrack (${offset})`);
    assert.equal(state.holds, 0, 'no hold');
    assert(state.snaps <= 1, 'only the lock at the start may snap');
    assert.equal(steps(settled).filter((step) => step.advance === 0).length, 0, 'no frame repeats a time');
    const exact = steps(settled).filter((step) => Math.abs(step.ratio - 1) < 1e-9).length;
    assert(exact >= 0.8 * (settled.length - 1), `coarse seed ${seed}: the dead zone leaves most frames at rate 1 (${exact} of ${settled.length - 1})`);
    naive += naiveZeroFrames(settled);
    total += settled.length - 1;
    worst = Math.max(worst, offset);
  }
  assert(naive > total / 4, `the readings alone repeat a time on many frames (${naive} of ${total})`);
  report.coarse60 = { frames: total, naiveRepeatedFrames: naive, clockRepeatedFrames: 0, maxOffsetMs: +(worst * 1000).toFixed(2) };
}

// ---- 30 Hz frames, very coarse readings (phone web views), drift ±1 % --------------------------
{
  const { rows } = run({ seconds: 6, fps: 30, frameJitter: 3 });
  monotonic(rows, '30 Hz');
  evenSteps(after(rows, 1000), '30 Hz');
  assert(maxAbs(offsets(after(rows, 1000))) <= 0.045, '30 Hz: within 45 ms');

  for (const range of [[0.08, 0.12], [0.2, 0.25]]) {
    const { rows, state } = run({ seconds: 8, audio: { steps: range } });
    const settled = after(rows, 2000);
    monotonic(rows, `readings every ${range} s`);
    evenSteps(settled, `readings every ${range} s`);
    assert(maxAbs(offsets(settled)) <= 0.030, `readings every ${range} s: within 30 ms`);
    assert.equal(state.holds, 0, `readings every ${range} s are not taken for stalls once their step is learned`);
    assert(state.stallLimit >= Math.min(MAX_STALL, 3 * range[0]) - 1e-9 && state.stallLimit <= MAX_STALL,
      `the stall limit follows the reading step, up to ${MAX_STALL} s (${state.stallLimit})`);
  }

  for (const drift of [0.01, -0.01]) {
    const { rows, state } = run({ seconds: 10, audio: { drift } });
    const settled = after(rows, 3000);
    monotonic(rows, `drift ${drift}`);
    evenSteps(settled, `drift ${drift}`);
    const offset = maxAbs(offsets(settled));
    assert(offset <= 0.030, `drift ${drift}: within 30 ms (${offset})`);
    const mean = steps(after(rows, 5000)).reduce((sum, step) => sum + step.ratio, 0) / steps(after(rows, 5000)).length;
    assert(Math.abs(mean - (1 + drift)) < 0.002, `drift ${drift}: the rate follows the soundtrack (${mean})`);
    assert.equal(state.holds + state.snaps, 1, `drift ${drift}: corrected by rate alone`);
    report[`drift${drift > 0 ? '+' : '-'}1%`] = { maxOffsetMs: +(offset * 1000).toFixed(2), meanRate: +mean.toFixed(5) };
  }
}

// ---- Start: hold at the start time until the soundtrack advances, then lock -------------------
{
  const { rows } = run({ seconds: 1, start: 12.5, audio: { latency: 0.12 } });
  assert.equal(rows[0].time, 12.5, 'the first frame shows the start time');
  const first = rows.findIndex((row) => row.mode === 'sync');
  assert(first > 0 && rows[first].t - 1000 >= 120, 'waits out the soundtrack start latency');
  for (const row of rows.slice(0, first)) assert.equal(row.time, 12.5, 'held at the start time while waiting');
  assert(rows[first].time - 12.5 <= 0.05 + 1e-9, 'locks within one reading step of the start');
  monotonic(rows, 'start');

  // A soundtrack that loads for 2 s after play() (WKWebView fetches the file then): the picture
  // waits at the start time for as long as it loads, and nothing of the song is skipped.
  const loadingUntilPlay = (audio, t) => t < audio.anchor;
  const late = run({ seconds: 4, start: 12.5, audio: { latency: 2 }, events: { 1: (audio, clock, t, host) => { host.loading = loadingUntilPlay; } } });
  const locked = late.rows.findIndex((row) => row.mode === 'sync');
  assert(late.rows.slice(0, locked).every((row) => row.mode === 'wait' && row.time === 12.5), 'late start: held at the start time while loading');
  assert(late.rows[locked].t - 1000 >= 2000, 'late start: locks once the soundtrack plays');
  assert.equal(late.state.realigns + late.audio.seeks, 0, 'late start: the soundtrack is not moved');
  assert(maxAbs(offsets(late.rows.slice(locked + 20))) <= 0.030, 'late start: within 30 ms');
  // Without the loading signal the clock gives up after 1 s and moves the soundtrack.
  const unknown = run({ seconds: 4, start: 12.5, audio: { latency: 2 } });
  assert(unknown.rows.some((row) => row.mode === 'free'), 'late start without the loading signal: frames after 1 s');
  assert.equal(unknown.state.realigns, 1);
  // Loading counts only until the soundtrack first plays: a later long stall while buffering
  // (readyState low again) still gives up after 1 s.
  const buffering = run({ seconds: 6, events: { 1: (audio, clock, t, host) => { host.loading = (track) => track.stalled; },
    120: (audio, clock, t) => audio.stall(t), 300: (audio, clock, t) => audio.resume(t) } });
  assert(buffering.rows.some((row) => row.k > 120 && row.k < 300 && row.mode === 'free'), 'buffering after the start: frames after 1 s');
  assert.equal(buffering.state.realigns, 1);
  // A new start (play, or a seek) waits for loading again.
  const again = run({ seconds: 6, audio: { latency: 0.03 }, events: {
    1: (audio, clock, t, host) => { host.loading = loadingUntilPlay; },
    120: (audio, clock, t, host) => { audio.pause(t); host.playing = false; host.pausedAt = clock.state().time; },
    150: (audio, clock, t, host) => { host.playing = true; audio.play(host.pausedAt, t + 1500); audio.anchor = t + 1500; clock.start(host.pausedAt, t); },
  } });
  const resumed = again.rows.filter((row) => row.k >= 150);
  const relock = resumed.findIndex((row) => row.mode === 'sync');
  assert(relock > 80 && resumed.slice(0, relock).every((row) => row.mode === 'wait' && row.time === resumed[0].time), 'a new start waits while loading');
  assert.equal(again.state.realigns, 0);
}

// ---- A single backward reading (a glitch) is ignored; a persistent backward step holds -------
{
  const glitch = run({ seconds: 4, events: { 120: (audio) => { audio.reported -= 0.2; } } });
  monotonic(glitch.rows, 'glitch');
  evenSteps(after(glitch.rows, 1000), 'glitch');
  assert.equal(glitch.state.holds, 0, 'one stray reading does not hold the picture');
  assert(maxAbs(offsets(after(glitch.rows, 1000))) <= 0.030, 'glitch: within 30 ms');

  // Two late readings in a row (a backward error needs one reading more than a forward one).
  let updates = 0;
  const twice = run({ seconds: 4, events: { 120: (audio, clock, t, host) => {
    host.reading = (track, now) => {
      const value = track.read(now);
      if (value !== host.lastValue) { host.lastValue = value; updates++; }
      return updates >= 2 && updates <= 3 ? value - 0.2 : value;
    };
  } } });
  assert(updates > 3);
  monotonic(twice.rows, 'two late readings');
  evenSteps(after(twice.rows, 1000), 'two late readings');
  assert.equal(twice.state.holds, 0, 'two late readings do not hold the picture');

  // One early reading leaves the rate alone (errors beyond snap are not filtered in).
  let early = false;
  const ahead = run({ seconds: 4, events: { 120: (audio, clock, t, host) => {
    host.reading = (track, now) => {
      const value = track.read(now);
      if (!early && value !== host.lastValue && host.lastValue !== undefined) { early = true; host.lastValue = value; return value + 0.2; }
      host.lastValue = value;
      return value;
    };
  } } });
  assert(early);
  const around = ahead.rows.filter((row) => row.k >= 110 && row.k <= 140);
  assert(around.every((row) => row.rate === around[0].rate), 'one early reading does not change the rate');
  assert.equal(ahead.state.snaps, 1, 'nor snap');

  const back = run({ seconds: 5, events: { 120: (audio, clock, t) => audio.jump(-0.2, t) } });
  monotonic(back.rows, 'backward step');
  assert.equal(back.state.holds, 1, 'a confirmed backward step holds once');
  const held = steps(back.rows).filter((step) => step.advance === 0);
  const heldFor = held.reduce((sum, step) => sum + step.interval, 0);
  assert(heldFor >= 0.12 && heldFor <= 0.22, `holds until the soundtrack catches up (${heldFor} s)`);
  const jumpAt = back.rows.find((row) => row.k === 120).t;
  const confirmed = back.rows.find((row) => row.holding);
  assert(confirmed.t - jumpAt <= (CONFIRM + 1) * 50 + 17, 'the hold starts within three readings (a late reading needs one more)');
  const resumed = back.rows.filter((row) => row.t >= jumpAt + 500);
  evenSteps(resumed, 'after the backward step');
  assert(maxAbs(offsets(resumed)) <= 0.030, 'after the backward step: within 30 ms');
  report.backwardStep = { heldMs: +(heldFor * 1000).toFixed(1), rewinds: 0 };
}

// ---- Forward errors: beyond snap they snap once, within it they are slewed out ----------------
{
  const jump = run({ seconds: 4, events: { 120: (audio, clock, t) => audio.jump(0.2, t) } });
  monotonic(jump.rows, 'forward jump');
  const big = steps(jump.rows).filter((step) => step.ratio > 1 + SLEW + 1e-9);
  assert.equal(big.length, 1, 'one forward snap');
  const jumpAt = jump.rows.find((row) => row.k === 120).t;
  assert(jump.rows.find((row) => row.k === big[0].k).t - jumpAt <= 2 * 50 + 17, 'snapped within two readings');
  assert(maxAbs(offsets(jump.rows.filter((row) => row.k > big[0].k))) <= 0.030, 'after the snap: within 30 ms');

  const small = run({ seconds: 5, events: { 120: (audio, clock, t) => audio.jump(0.035, t) } });
  monotonic(small.rows, 'small offset');
  evenSteps(after(small.rows, 1000), 'small offset: slewed, not snapped');
  assert.equal(small.state.snaps, 1, 'only the start lock snapped');
  const later = small.rows.filter((row) => row.t >= small.rows.find((item) => item.k === 120).t + 1500);
  assert(maxAbs(offsets(later)) <= 0.020, 'the 35 ms offset is worked off within 1.5 s');
}

// ---- Seek and pause/resume -------------------------------------------------------------------
{
  // A seek while playing: the host seeks the soundtrack and the clock (mv-studio.js seek()).
  const sought = run({ seconds: 4, events: { 120: (audio, clock, t) => { audio.seek(30, t); clock.seek(30, true); } } });
  const index = sought.rows.findIndex((row) => row.k === 120);
  assert.equal(sought.rows[index].time, 30, 'the seek frame shows the sought time');
  monotonic(sought.rows.slice(index), 'after the seek');
  const relocked = sought.rows.slice(index).find((row) => row.mode === 'sync');
  assert(relocked && relocked.t - sought.rows[index].t <= 30 + 2 * 50 + 17, 'locks again within the latency and two readings');
  assert(maxAbs(offsets(sought.rows.filter((row) => row.t >= relocked.t + 200))) <= 0.030, 'after the seek: within 30 ms');

  // A seek to the time already shown with the soundtrack left alone (an edit while playing) keeps the lock.
  const edit = run({ seconds: 3, events: { 120: (audio, clock) => clock.seek(clock.state().time, false) } });
  evenSteps(after(edit.rows, 1000), 'an edit while playing');
  assert(edit.rows.every((row, i) => i < 5 || row.mode === 'sync'), 'stays locked');
  // A seek to another time with the soundtrack left alone (a plugin's {audio: false} seek while
  // playing): the next frame shows the sought time and asks the host to move the soundtrack
  // there, forward and backward alike; the picture then goes on from the sought time.
  for (const by of [0.03, 0.3, 2, -0.3, -2]) {
    const plugin = run({ seconds: 4, events: { 120: (audio, clock, t, host) => { host.sought = clock.state().time + by; clock.seek(host.sought, false); } } });
    const label = `plugin seek by ${by} s while playing`;
    const index = plugin.rows.findIndex((row) => row.k === 120), jumped = plugin.rows[index];
    assert.equal(jumped.mode, 'wait', `${label}: waits for the soundtrack`);
    assert.equal(jumped.realign, true, `${label}: asks the host to move the soundtrack`);
    assert.equal(plugin.audio.seeks, 1, `${label}: the soundtrack is moved once`);
    const sought = jumped.time;
    assert(Math.abs(sought - (plugin.rows[index - 1].time + by)) < 1e-9, `${label}: shows the sought time`);
    monotonic(plugin.rows.slice(index), label);
    assert.equal(plugin.state.holds, 0, `${label}: no hold`);
    const relocked = plugin.rows.slice(index).find((row) => row.mode === 'sync');
    assert(relocked.time - sought <= 0.05 + 1e-9, `${label}: goes on from the sought time`);
    assert(maxAbs(offsets(plugin.rows.slice(index + 30))) <= 0.030, `${label}: in sync afterwards`);
  }
  // The same seek while paused: the soundtrack is moved when playback starts again.
  let pausedAt = NaN;
  const pausedSeek = run({ seconds: 4, events: {
    100: (audio, clock, t, host) => { audio.pause(t); host.playing = false; pausedAt = clock.state().time + 1; clock.seek(pausedAt, false); },
    130: (audio, clock, t, host) => { host.playing = true; audio.play(audio.base, t); clock.start(pausedAt, t); },
  } });
  const replay = pausedSeek.rows.find((row) => row.k === 130);
  assert(replay.realign && replay.time === pausedAt, 'paused plugin seek: the soundtrack is moved to the sought time at play');
  assert.equal(pausedSeek.audio.seeks, 1);
  assert(maxAbs(offsets(pausedSeek.rows.filter((row) => row.k >= 160))) <= 0.030, 'paused plugin seek: in sync after play');
  // A later seek that moves the soundtrack itself cancels the request.
  const cancelled = run({ seconds: 3, events: { 120: (audio, clock, t) => {
    clock.seek(clock.state().time + 1, false);
    audio.seek(20, t);
    clock.seek(20, true);
  } } });
  assert(!cancelled.rows.some((row) => row.realign), 'a seek that moved the soundtrack: no request');
  assert.equal(cancelled.audio.seeks, 1);
  // Without a soundtrack there is nothing to move.
  const silentSeek = run({ seconds: 2, soundtrack: false, events: { 60: (audio, clock) => clock.seek(30, false) } });
  assert(!silentSeek.rows.some((row) => row.realign), 'no soundtrack: no request');
  // Moving the soundtrack (an offset change: seek(time, true)) resynchronises.
  const offset = run({ seconds: 3, events: { 120: (audio, clock, t) => { const now = clock.state().time; audio.seek(now, t); clock.seek(now, true); } } });
  monotonic(offset.rows, 'offset change');
  assert.equal(offset.rows.find((row) => row.k === 120).mode, 'wait', 'waits for the moved soundtrack');

  // Pause: the host stops the frames and the soundtrack; play starts the clock at the paused time.
  const paused = run({ seconds: 5, events: {
    100: (audio, clock, t, host) => { audio.pause(t); host.playing = false; host.pausedAt = clock.state().time; },
    160: (audio, clock, t, host) => { host.playing = true; audio.play(host.pausedAt, t); clock.start(host.pausedAt, t); },
  } });
  const resume = paused.rows.findIndex((row) => row.k === 160);
  assert(Math.abs(paused.rows[resume - 1].time - paused.rows[resume - 1].truth) <= 0.030, 'in sync when paused');
  assert.equal(paused.rows[resume].time, paused.rows[resume - 1].time, 'resumes from the paused time');
  monotonic(paused.rows, 'pause and resume');
  assert(maxAbs(offsets(paused.rows.filter((row) => row.t >= paused.rows[resume].t + 300))) <= 0.030, 'after resume: within 30 ms');
}

// ---- Stalls, buffering and an unusable soundtrack ----------------------------------------------
{
  // A 0.5 s stall: the picture stops within the stall limit, then follows the resumed soundtrack.
  const stall = run({ seconds: 5, events: { 120: (audio, clock, t) => audio.stall(t), 150: (audio, clock, t) => audio.resume(t) } });
  monotonic(stall.rows, 'stall');
  const stallAt = stall.rows.find((row) => row.k === 120).t, frozen = stall.rows.find((row) => row.k === 149);
  assert(stall.state.stallLimit <= 3 * 0.05 + 1e-9, `three reading steps of at most 50 ms (${stall.state.stallLimit})`);
  assert(frozen.time - frozen.truth <= stall.state.stallLimit + 1 / 60 + DEAD_ZONE,
    `leads the stalled soundtrack by at most the stall limit and a frame (${frozen.time - frozen.truth})`);
  assert(stall.rows.some((row) => row.t > stallAt && row.mode === 'wait'), 'waits during the stall');
  assert(maxAbs(offsets(stall.rows.filter((row) => row.t >= stallAt + 900))) <= 0.030, 'after the stall: within 30 ms');

  // Seeking or buffering (ready false): hold, then follow.
  const buffering = run({ seconds: 4, events: { 120: (audio, clock, t, host) => { audio.stall(t); host.ready = false; },
    140: (audio, clock, t, host) => { audio.resume(t); host.ready = true; } } });
  monotonic(buffering.rows, 'buffering');
  const waiting = buffering.rows.filter((row) => row.k > 120 && row.k < 140);
  assert(waiting.every((row) => row.mode === 'wait' && row.time === waiting[0].time), 'held while buffering');
  assert(maxAbs(offsets(buffering.rows.filter((row) => row.k >= 170))) <= 0.030, 'after buffering: within 30 ms');

  // A 3 s stall: after giveUp the frames drive the time (the no-soundtrack behaviour); when the
  // soundtrack resumes far behind, the clock asks the host to move it to the picture.
  const long = run({ seconds: 7, events: { 120: (audio, clock, t) => audio.stall(t), 300: (audio, clock, t) => audio.resume(t) } });
  monotonic(long.rows, 'long stall');
  const free = long.rows.filter((row) => row.k > 120 && row.k < 300 && row.mode === 'free');
  assert(free.length > 60, 'frames only after giveUp');
  // Counted from the soundtrack's last new reading, not from when the stall was noticed.
  const lastNew = long.rows.filter((row, i) => i > 0 && row.k <= 300 && row.reading !== long.rows[i - 1].reading).at(-1);
  const gaveUp = free[0].t - lastNew.t;
  assert(gaveUp > GIVE_UP * 1000 && gaveUp <= GIVE_UP * 1000 + 1000 / 60 + 1e-6, `gives up 1 s after the last new reading (${gaveUp} ms)`);
  for (const step of steps(free)) assert(Math.abs(step.advance - step.interval) < 1e-9, 'free-running advances by the frame interval');
  assert.equal(long.state.realigns, 1, 'one realignment');
  assert(!long.rows.some((row) => row.holding), 'the far-behind soundtrack is moved, not waited for');
  assert.equal(long.audio.seeks, 1, 'the host moved the soundtrack');
  assert(maxAbs(offsets(long.rows.filter((row) => row.k >= 330))) <= 0.030, 'after the realignment: within 30 ms');

  // Two long stalls in one playback: the soundtrack followed the first realignment, so the
  // second long stall is realigned as well.
  const stop = (audio, clock, t) => audio.stall(t), go = (audio, clock, t) => audio.resume(t);
  const twice = run({ seconds: 14, events: { 120: stop, 300: go, 540: stop, 720: go } });
  monotonic(twice.rows, 'two long stalls');
  assert.equal(twice.state.realigns, 2, 'two long stalls: two realignments');
  assert.equal(twice.audio.seeks, 2, 'two long stalls: the host moved the soundtrack twice');
  assert.equal(twice.state.ignored, false, 'two long stalls: the soundtrack is still used');
  assert(twice.rows.filter((row) => row.k >= 400 && row.k < 540).every((row) => row.mode === 'sync'), 'in sync between the stalls');
  assert(maxAbs(offsets(twice.rows.filter((row) => row.k >= 400 && row.k < 540))) <= 0.030, 'between the stalls: within 30 ms');
  assert(twice.rows.slice(-60).every((row) => row.mode === 'sync'), 'two long stalls: following the soundtrack at the end');
  assert(maxAbs(offsets(twice.rows.filter((row) => row.k >= 760))) <= 0.030, 'after the second stall: within 30 ms');
  // A soundtrack that followed the first realignment but not the second is ignored.
  const second = run({ seconds: 14, events: { 120: stop, 300: go, 540: (audio, clock, t) => { audio.seekable = false; audio.stall(t); },
    720: go } });
  monotonic(second.rows, 'second realignment not followed');
  assert.equal(second.state.realigns, 2);
  assert.equal(second.state.ignored, true, 'the soundtrack that did not follow the second realignment is ignored');
  assert(second.rows.slice(-60).every((row) => row.mode === 'free'), 'frames only after it');

  // A slow seek (a soundtrack over the network on a phone): the clock waits for the seeking
  // soundtrack however long the seek takes, and does not give up on it.
  const slow = run({ seconds: 6, audio: { seekTime: 1.5 }, events: { 120: (audio, clock, t) => { audio.seek(30, t); clock.seek(30, true); } } });
  monotonic(slow.rows, 'slow seek');
  const seeking = slow.rows.filter((row) => row.k >= 120 && row.seeking);
  assert(seeking.length > 80, 'frames while the soundtrack seeks');
  assert(seeking.every((row) => row.mode === 'wait' && row.time === 30), 'held at the sought time while the soundtrack seeks');
  assert.equal(slow.state.realigns, 0, 'slow seek: no realignment');
  assert(maxAbs(offsets(slow.rows.filter((row) => row.k >= 240))) <= 0.030, 'after the slow seek: within 30 ms');
  // A long stall whose realignment seek is slow: still in sync afterwards.
  const slowRealign = run({ seconds: 9, audio: { seekTime: 1.6 }, events: { 120: stop, 300: go } });
  monotonic(slowRealign.rows, 'slow realignment seek');
  assert.equal(slowRealign.state.realigns, 1);
  assert.equal(slowRealign.state.ignored, false, 'slow realignment seek: the soundtrack is still used');
  const realignedAt = slowRealign.rows.find((row) => row.realign);
  assert(slowRealign.rows.filter((row) => row.seeking && row.t > realignedAt.t).every((row) => row.mode === 'wait' && row.time === realignedAt.time),
    'held at the realigned time while the soundtrack seeks');
  assert(slowRealign.rows.slice(-60).every((row) => row.mode === 'sync'), 'following the soundtrack at the end');
  assert(maxAbs(offsets(slowRealign.rows.slice(-120))) <= 0.030, 'after the slow realignment seek: within 30 ms');

  // A soundtrack that does not follow the realignment is ignored until the next start or seek.
  const stuck = run({ seconds: 7, audio: { seekable: false }, events: { 120: (audio, clock, t) => audio.stall(t), 300: (audio, clock, t) => audio.resume(t) } });
  monotonic(stuck.rows, 'unseekable');
  assert.equal(stuck.state.realigns, 1);
  assert.equal(stuck.state.ignored, true, 'the lagging soundtrack is ignored');
  assert(stuck.rows.slice(-60).every((row) => row.mode === 'free'), 'frames only');
  const restarted = run({ seconds: 8, audio: { seekable: false }, events: { 120: (audio, clock, t) => audio.stall(t),
    300: (audio, clock, t) => audio.resume(t), 420: (audio, clock, t) => clock.start(audio.truth(t), t) } });
  assert.equal(restarted.rows.find((row) => row.k === 419).mode, 'free');
  assert(restarted.rows.slice(-50).every((row) => row.mode === 'sync'), 'a new start uses the soundtrack again');

  // Never advancing (a broken media clock): hold for giveUp, then frames only.
  const broken = run({ seconds: 3, events: { 1: (audio, clock, t, host) => { host.reading = () => 0; } } });
  monotonic(broken.rows, 'broken');
  const freeFrom = broken.rows.find((row) => row.mode === 'free');
  assert(Math.abs(freeFrom.t - 1000 - GIVE_UP * 1000) <= 17, 'gives up after 1 s');
  for (const step of steps(broken.rows.filter((row) => row.mode === 'free'))) assert(Math.abs(step.advance - step.interval) < 1e-9);

  // The browser pauses the soundtrack (an interruption) and resumes it where it stopped.
  const interrupted = run({ seconds: 6, events: {
    120: (audio, clock, t) => audio.pause(t),
    240: (audio, clock, t) => audio.play(audio.base, t),
  } });
  monotonic(interrupted.rows, 'interrupted');
  const unpaused = interrupted.rows.filter((row) => row.k > 120 && row.k < 240);
  assert(unpaused.every((row) => row.mode === 'free'), 'frames only while the browser holds the soundtrack');
  assert.equal(interrupted.state.realigns, 1, 'the soundtrack is moved to the picture when it comes back');
  assert(maxAbs(offsets(interrupted.rows.filter((row) => row.k >= 270))) <= 0.030, 'after the interruption: within 30 ms');

  // Ended (a soundtrack shorter than the MV): frames only.
  const ended = run({ seconds: 3, events: { 120: (audio) => { audio.ended = true; } } });
  monotonic(ended.rows, 'ended');
  for (const step of steps(ended.rows.filter((row) => row.k > 121))) assert(Math.abs(step.advance - step.interval) < 1e-9);
}

// ---- No soundtrack: exactly the frame clock, as before ------------------------------------------
{
  // A seek while playing (frame 60) goes on from the sought time by the frame interval, as the
  // frame clock did.
  const { rows } = run({ seconds: 2, soundtrack: false, frameJitter: 4, start: 3, events: { 60: (audio, clock) => clock.seek(20, true) } });
  assert(rows.every((row) => row.mode === 'free'));
  let previous = { t: 1000, time: 3 };
  for (const row of rows) {
    const from = row.k === 60 ? 20 : previous.time;
    assert(Math.abs(row.time - (from + (row.t - previous.t) / 1000)) < 1e-12, `time + frame interval (frame ${row.k})`);
    previous = row;
  }
  // A start without a frame timestamp: the time towards giveUp counts from the first frame.
  {
    const clock = Clock.create();
    clock.start(5, NaN);
    const out = [];
    for (let k = 0; k <= 70; k++) out.push(clock.next(2000 + k * 1000 / 60, 5, true));
    assert.equal(out[0].time, 5, 'the first frame shows the start time');
    assert.equal(out.findIndex((step) => step.mode === 'free'), 61, 'gives up 1 s after the first frame');
  }
  // A frame timestamp before the start timestamp (a rAF time older than the click) does not go back.
  const clock = Clock.create();
  clock.start(5, 1000);
  assert.equal(clock.next(990, NaN).time, 5, 'never below the start time');
}

// ---- A long frame gap (a hitch) resynchronises at once -------------------------------------------
{
  const gap = run({ seconds: 4, frames: (k) => k === 120 ? 900 : 1000 / 60, audio: { drift: 0.01 } });
  monotonic(gap.rows, 'gap');
  const index = gap.rows.findIndex((row) => row.k === 120);
  assert(Math.abs(gap.rows[index].time - gap.rows[index].truth) <= 0.030, 'in sync on the frame after the gap');
  // The soundtrack skipped during the gap: corrected on the frame after it, with no confirmation.
  const skipped = run({ seconds: 4, frames: (k) => k === 120 ? 900 : 1000 / 60, events: { 120: (audio, clock, t) => audio.jump(0.3, t - 450) } });
  monotonic(skipped.rows, 'skip during a gap');
  const skip = skipped.rows.find((row) => row.k === 120);
  assert(Math.abs(skip.time - skip.truth) <= 0.030, `the skip is caught up on the frame after the gap (${skip.time - skip.truth})`);
  // A rate correction in progress is not applied over the whole of a long gap.
  const slewing = run({ seconds: 6, frames: (k) => k === 150 ? 3000 : 1000 / 60, events: { 120: (audio, clock, t) => audio.jump(0.04, t) } });
  monotonic(slewing.rows, 'gap while slewing');
  assert(slewing.rows.find((row) => row.k === 149).rate > 1.01, 'slewing when the gap starts');
  assert.equal(slewing.state.holds, 0, 'no hold after the gap');
  const landed = slewing.rows.find((row) => row.k === 150);
  assert(Math.abs(landed.time - landed.truth) <= SNAP, `the slew carries on after the gap, below snap (${landed.time - landed.truth})`);
}

// ---- Exact readings: the rules at lock, confirmation counts and hold release --------------------
// The soundtrack is read on every 60 Hz frame with no coarse steps, so the clock's target is the
// soundtrack's position itself and each rule shows on a known frame. The soundtrack starts at
// `audioStart` (the clock at `start`) one frame after the first, by default so that it reaches
// `start` on the frame the clock locks; `reading(k, truth)` may change a frame's reading; a
// realignment moves the soundtrack to the picture, playing again a frame later.
function exact({ start = 10, audioStart = start - 1 / 60, frames = 150, reading = null } = {}) {
  const clock = Clock.create(), interval = 1000 / 60, writes = [];
  let base = audioStart, anchor = 1000 + interval;
  clock.start(start, 1000);
  const rows = [];
  for (let k = 1; k <= frames; k++) {
    const t = 1000 + k * interval;
    const truth = base + Math.max(0, t - anchor) / 1000;
    const out = clock.next(t, reading ? reading(k, truth) : truth, true);
    rows.push({ k, t, truth, time: out.time, mode: out.mode, holding: out.holding, rate: out.rate, realign: out.realign });
    if (out.realign) { writes.push(out.time); base = out.time; anchor = t + interval; }
  }
  return { rows, writes, state: clock.state(), interval: interval / 1000 };
}
{
  const lockOf = (rows) => rows.find((row) => row.mode === 'sync');
  // The soundtrack lands a little behind the picture (a seek to a codec frame before the sought
  // time): the picture keeps its time and slews, it neither steps back nor holds.
  for (const behind of [0.012, 0.03, 0.045]) {
    const { rows, state, writes } = exact({ audioStart: 10 - 1 / 60 - behind });
    const lock = lockOf(rows);
    assert(Math.abs(lock.truth - 10 + behind) < 1e-9, 'locks with the soundtrack behind the picture');
    assert.equal(lock.time, 10, `${behind * 1000} ms behind: the picture keeps its time at the lock`);
    monotonic(rows, `${behind * 1000} ms behind at the lock`);
    evenSteps(rows.slice(rows.indexOf(lock)), `${behind * 1000} ms behind at the lock`);
    assert.equal(state.holds + state.snaps + state.realigns + writes.length, 0, `${behind * 1000} ms behind: no hold, snap or realignment`);
    const slowest = Math.min(...rows.map((row) => row.rate));
    assert(slowest < 1, `${behind * 1000} ms behind: slowed down to catch up`);
    // (error - dead zone) / slewTime 0.5 s, at most 3 %.
    if (behind >= 0.03) assert(Math.abs(slowest - (1 - SLEW)) < 1e-12, `${behind * 1000} ms behind: at most 3 % slower (${slowest})`);
    else assert(Math.abs(slowest - (1 - (behind - DEAD_ZONE) / 0.5)) < 1e-9, `${behind * 1000} ms behind: slewed over 0.5 s (${slowest})`);
    assert(maxAbs(offsets(rows.slice(-30))) <= DEAD_ZONE + 0.002, `${behind * 1000} ms behind: worked off`);
  }
  // Ahead of the picture at the lock: moves forward to the soundtrack at once.
  {
    const { rows, state } = exact({ audioStart: 10.2 });
    const lock = lockOf(rows);
    assert.equal(lock.time, lock.truth, 'ahead at the lock: shows the soundtrack time');
    assert.equal(state.snaps, 1);
  }
  // 0.1-0.5 s behind at the lock: hold the picture until the soundtrack reaches it (no realign);
  // the frame that lets go advances by no more than its own interval.
  for (const behind of [0.1, 0.3, 0.45]) {
    const { rows, state, writes, interval } = exact({ audioStart: 10 - 1 / 60 - behind });
    monotonic(rows, `${behind} s behind at the lock`);
    assert.equal(state.holds, 1, `${behind} s behind: holds`);
    assert.equal(state.realigns + writes.length, 0, `${behind} s behind: the soundtrack is not moved`);
    const release = rows.findIndex((row, i) => i > 0 && rows[i - 1].holding && !row.holding);
    assert(release > 0, `${behind} s behind: the hold ends`);
    assert(rows.slice(0, release).every((row) => row.time === 10), `${behind} s behind: held at the start time`);
    const advance = rows[release].time - rows[release - 1].time;
    assert(advance >= 0 && advance <= interval + 1e-9, `${behind} s behind: the release frame advances ${advance * 1000} ms`);
    assert.equal(rows[release].time, rows[release].truth, `${behind} s behind: continues from the soundtrack's time`);
    assert(Math.abs((rows[release].t - rows[0].t) / 1000 - behind) <= 2 * interval + 1e-9, `${behind} s behind: held for about ${behind} s`);
    evenSteps(rows.slice(release), `${behind} s behind: after the hold`);
  }
  // More than 0.5 s behind at the lock: the soundtrack is moved to the picture, which never holds.
  for (const behind of [0.55, 0.8]) {
    const { rows, state, writes } = exact({ audioStart: 10 - 1 / 60 - behind });
    monotonic(rows, `${behind} s behind at the lock`);
    assert.equal(state.holds, 0, `${behind} s behind: no hold`);
    assert.deepEqual(writes, [10], `${behind} s behind: the soundtrack is moved once, to the picture's time`);
    assert.equal(rows.filter((row) => row.realign).length, 1);
    assert(rows.slice(-60).every((row) => row.mode === 'sync' && Math.abs(row.time - row.truth) < 1e-9), `${behind} s behind: in sync afterwards`);
  }

  // Confirmation counts: a forward error beyond snap acts on the second reading that shows it, a
  // backward one (late readings) on the third.
  {
    const { rows, state } = exact({ reading: (k, truth) => truth + (k >= 60 ? 0.2 : 0) });
    const snapped = steps(rows).filter((step) => step.ratio > 1 + SLEW + 1e-9);
    assert.deepEqual(snapped.map((step) => step.k), [61], 'a forward jump snaps on the second reading that shows it');
    assert.equal(state.snaps, 1);
    const back = exact({ reading: (k, truth) => truth - (k >= 60 ? 0.2 : 0) });
    assert.equal(back.rows.find((row) => row.holding).k, 62, 'a backward jump holds on the third reading that shows it');
    // A single reading beyond snap is no confirmation, nor are two that disagree in sign.
    const single = exact({ reading: (k, truth) => truth + (k === 60 ? 0.2 : 0) });
    assert.equal(single.state.snaps, 0, 'one early reading: no snap');
    evenSteps(single.rows.slice(30), 'one early reading');
  }
  // Outliers of alternating sign: after a lock 45 ms behind (the picture leads), a reading low by
  // 10 ms is beyond snap below the picture, and one 0.1 s high right after it beyond snap above:
  // neither direction is confirmed.
  {
    const { rows, state } = exact({ audioStart: 10 - 1 / 60 - 0.045, reading: (k, truth) => truth + (k === 4 ? -0.01 : k === 5 ? 0.1 : 0) });
    const lock = lockOf(rows);
    assert.equal(lock.k, 2);
    assert.equal(state.snaps + state.holds, 0, 'alternating outliers: no snap and no hold');
    monotonic(rows, 'alternating outliers');
    evenSteps(rows.slice(1), 'alternating outliers');
  }
  // A frame gap just over 250 ms resynchronises at once, a soundtrack skip during it included.
  {
    const gap = run({ seconds: 4, frames: (k) => k === 120 ? 300 : 1000 / 60, events: { 120: (audio, clock, t) => audio.jump(0.3, t - 150) } });
    const skip = gap.rows.find((row) => row.k === 120);
    assert(Math.abs(skip.time - skip.truth) <= 0.030, `a 300 ms gap: the skip is caught up on the frame after it (${skip.time - skip.truth})`);
  }
}

// ---- Heavy load: irregular frames (16-230 ms) and stale readings --------------------------------
// Under load the media element sometimes hands out a position up to 200 ms old (the audit of
// headless Chromium saw reading steps differ from frame steps by -231 to +229 ms).
{
  let worst = 0, naive = 0, total = 0, backwardsNaive = 0;
  for (let seed = 1; seed <= 6; seed++) {
    const intervals = [16.7, 16.7, 16.7, 33.3, 50, 120, 230], late = rng(seed + 100);
    const { rows } = run({ seed, seconds: 8, frames: (k, random) => intervals[Math.floor(random() * intervals.length)], events: {
      1: (audio, clock, t, host) => {
        host.reading = (track, now) => {
          const value = track.read(now);
          return late() < 0.15 ? Math.max(0, track.truth(now - 200 * late())) : value;
        };
      },
    } });
    monotonic(rows, `load seed ${seed}`);
    const settled = after(rows, 1000);
    worst = Math.max(worst, maxAbs(offsets(settled)));
    const naiveSteps = steps(settled.map((row) => ({ ...row, time: row.reading })));
    naive += naiveSteps.filter((step) => step.advance === 0).length;
    backwardsNaive += naiveSteps.filter((step) => step.advance < 0).length;
    total += naiveSteps.length;
  }
  assert(worst <= 0.1, `under load the offset stays within 100 ms (${worst})`);
  assert(backwardsNaive > 0, 'the readings alone go backwards under load');
  report.load = { frames: total, naiveRepeatedFrames: naive, naiveBackwardFrames: backwardsNaive, clockBackwardFrames: 0,
    maxOffsetMs: +(worst * 1000).toFixed(1) };
}

console.log(JSON.stringify({ status: 'PASS', report }));
