/* MV Studio playback clock (mv-studio-playback-clock.js) against simulated clocks.

   A simulated soundtrack plays at wall-clock rate (optionally drifting by ±1%) after a start
   latency, and reports its position only at coarse update moments (20-50 ms apart unless
   stated, with optional reading jitter), as browsers and phone web views do. Display frames
   arrive at 60 Hz (or 30 Hz) with optional timestamp jitter. The host feeds the clock one
   reading per frame, as mv-studio.js tick() does, and moves the soundtrack when the clock
   asks it to realign.

   Bounds checked (DEFAULTS): once locked, every frame advances by its frame interval times
   a rate within 1 ± maxSlew (3 %), never by zero and never backwards, except on the frames
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
const D = Clock.DEFAULTS;

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
function soundtrack(random, { steps = [0.02, 0.05], jitter = 0, drift = 0, latency = 0.03, seekable = true } = {}) {
  const s = { playing: false, stalled: false, paused: true, ended: false, base: 0, anchor: 0, reported: 0, next: Infinity, seeks: 0 };
  const step = () => (steps[0] + (steps[1] - steps[0]) * random()) * 1000;
  s.truth = (t) => s.playing && !s.stalled ? s.base + Math.max(0, t - s.anchor) / 1000 * (1 + drift) : s.base;
  s.play = (position, t) => {
    Object.assign(s, { base: position, anchor: t + latency * 1000, playing: true, paused: false, stalled: false, reported: position });
    s.next = t + step();
  };
  s.pause = (t) => { s.base = s.reported = s.truth(t); s.playing = false; s.paused = true; };
  s.seek = (position, t) => {
    s.seeks++;
    if (!seekable) return;
    Object.assign(s, { base: position, anchor: t + latency * 1000, reported: position });
    s.next = t + step();
  };
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
  const frame = 1000 / fps, host = { reading: null, ready: true, playing: true };
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
    const out = clock.next(t, reading, host.ready);
    if (out.realign) audio.seek(out.time, t);
    rows.push({ k, t, time: out.time, truth: audio.truth(t), reading, mode: out.mode, holding: out.holding, rate: out.rate, realign: out.realign });
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
    assert(step.ratio >= 1 - D.maxSlew - slack && step.ratio <= 1 + D.maxSlew + slack,
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
    assert(state.stallLimit >= Math.min(D.maxStall, D.stallSteps * range[0]) - 1e-9, 'the stall limit follows the reading step');
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
  assert(confirmed.t - jumpAt <= (D.confirm + 1) * 50 + 17, 'the hold starts within three readings (a late reading needs one more)');
  const resumed = back.rows.filter((row) => row.t >= jumpAt + 500);
  evenSteps(resumed, 'after the backward step');
  assert(maxAbs(offsets(resumed)) <= 0.030, 'after the backward step: within 30 ms');
  report.backwardStep = { heldMs: +(heldFor * 1000).toFixed(1), rewinds: 0 };
}

// ---- Forward errors: beyond snap they snap once, within it they are slewed out ----------------
{
  const jump = run({ seconds: 4, events: { 120: (audio, clock, t) => audio.jump(0.2, t) } });
  monotonic(jump.rows, 'forward jump');
  const big = steps(jump.rows).filter((step) => step.ratio > 1 + D.maxSlew + 1e-9);
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
  // A seek to another time with the soundtrack left alone starts over from that time.
  const plugin = run({ seconds: 3, events: { 120: (audio, clock) => clock.seek(clock.state().time + 0.3, false) } });
  const jumped = plugin.rows.find((row) => row.k === 120), before = plugin.rows.find((row) => row.k === 119);
  assert.equal(jumped.mode, 'wait', 'waits for the soundtrack');
  assert(Math.abs(jumped.time - (before.time + 0.3)) < 1e-9, 'shows the sought time');
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
  assert(frozen.time - frozen.truth <= stall.state.stallLimit + 1 / 60 + D.deadZone,
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
  for (const step of steps(free)) assert(Math.abs(step.advance - step.interval) < 1e-9, 'free-running advances by the frame interval');
  assert.equal(long.state.realigns, 1, 'one realignment');
  assert(!long.rows.some((row) => row.holding), 'the far-behind soundtrack is moved, not waited for');
  assert.equal(long.audio.seeks, 1, 'the host moved the soundtrack');
  assert(maxAbs(offsets(long.rows.filter((row) => row.k >= 330))) <= 0.030, 'after the realignment: within 30 ms');

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
  assert(Math.abs(freeFrom.t - 1000 - D.giveUp * 1000) <= 17, 'gives up after giveUp');
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
  const { rows } = run({ seconds: 2, soundtrack: false, frameJitter: 4, start: 3 });
  assert(rows.every((row) => row.mode === 'free'));
  let previous = { t: 1000, time: 3 };
  for (const row of rows) {
    assert(Math.abs(row.time - (previous.time + (row.t - previous.t) / 1000)) < 1e-12, 'time + frame interval');
    previous = row;
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
  assert(Math.abs(landed.time - landed.truth) <= D.snap, `the slew carries on after the gap, below snap (${landed.time - landed.truth})`);
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
