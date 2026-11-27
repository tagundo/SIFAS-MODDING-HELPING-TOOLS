/* MV Studio real-time playback clock: the song time shown while the MV plays.

   Browsers report a soundtrack's media clock (HTMLMediaElement.currentTime) in coarse,
   uneven steps, and phone web views (Android WebView, WKWebView) more coarsely still.
   Shown directly, such a clock repeats a time on some display frames and jumps on others
   (judder), and a backward step makes the scene reset its physics ("clock-rewind" in
   mv-studio-scene.js). This clock advances with the display frames (requestAnimationFrame
   timestamps) and is slewed toward the soundtrack:

   - the target is the soundtrack's last reading plus the time since that reading was first
     seen, up to the stall limit;
   - a filtered error inside the dead zone is left alone; beyond it the rate changes by at
     most maxSlew (a few percent), so successive frames advance evenly and drift is followed;
   - an error beyond `snap` that `confirm` fresh readings agree on is corrected at once:
     forward by moving to the soundtrack's time, backward by holding the picture until the
     soundtrack catches up, or, beyond `realign`, by asking the host to move the soundtrack
     to the picture (again only once the soundtrack has followed: one that still lags after
     a realignment is ignored until the next start or seek).
     A reading that falls behind the soundtrack's course is taken for a late one and used
     only when `confirm` + 1 readings in a row agree (it still shows that the soundtrack's
     clock is running, so it does not count toward a stall);
   - after start() or seek(), and whenever the soundtrack stops or resumes (seeking,
     buffering, a stall, a long frame gap), the clock holds and waits for the soundtrack to
     advance, then locks onto it with no confirmation;
   - with no soundtrack, one the browser paused or ended, or one not advancing for `giveUp`
     (not counting the time it spends seeking, nor, before it first advances after start(),
     loading), the time advances with the frames, as it does without a soundtrack;
   - during playback the time it returns is never below the last one.

   Pure state: mv-studio.js feeds it one reading per animation frame. Frame captures step
   MVStudioScene.playbackFrame at fixed times and do not use it. */
(function (global) {
  "use strict";

  const DEFAULTS = Object.freeze({
    deadZone: 0.008, // s: filtered errors this small are left alone
    slewTime: 0.5, // s: an error beyond the dead zone is worked off over about this long
    maxSlew: 0.03, // the rate stays within 1 ± maxSlew
    filterTime: 0.2, // s: time constant of the error filter
    snap: 0.05, // s: a confirmed error beyond this is corrected at once
    realign: 0.5, // s: a soundtrack this far behind the picture is moved to it
    confirm: 2, // fresh readings that must agree on an error beyond `snap`
    stallSteps: 3, // no new reading for this many typical soundtrack steps: stalled
    minStall: 0.1, maxStall: 0.5, // s: bounds of that stall limit
    giveUp: 1, // s: a soundtrack not advancing this long is not used
    maxGap: 0.25, // s: a longer frame gap resynchronises
  });
  const finite = Number.isFinite;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  function create(options = {}) {
    const o = { ...DEFAULTS, ...options };
    let time = 0; // the time last returned (s)
    let last = NaN; // timestamp of the last frame (ms)
    let mode = "wait"; // "wait": hold for the soundtrack; "sync": follow it; "free": frames only
    let rate = 1, error = 0, holding = false, realigned = false, ignored = false;
    let locked = false; // the soundtrack has advanced since start()
    let audio = NaN, seen = NaN; // the reading followed (s) and when it was first seen (ms)
    let read = NaN, alive = NaN; // the latest distinct reading, used or not, and when it came (ms)
    let since = NaN; // when waiting began (ms)
    let step = 1 / 30; // typical advance between distinct readings (s)
    let outliers = 0, outlierSign = 0, late = 0;
    const counts = { snaps: 0, holds: 0, realigns: 0 };

    const stallLimit = () => clamp(o.stallSteps * step, o.minStall, o.maxStall);

    function forget(now) {
      audio = seen = read = alive = NaN;
      since = now;
      outliers = outlierSign = late = 0;
    }

    function wait(now, from = now) {
      mode = "wait";
      since = finite(from) ? from : now;
      holding = false;
      rate = 1;
      error = 0;
      outliers = outlierSign = late = 0;
    }

    // Playback starts at `value` (s) at frame timestamp `now` (ms).
    function start(value, now) {
      time = finite(value) ? value : 0;
      last = finite(now) ? now : NaN;
      realigned = ignored = locked = false;
      forget(last);
      wait(last);
    }

    // The playhead moved to `value`, or the soundtrack was moved (`moved`): resynchronise.
    // A seek to the time already shown that leaves the soundtrack alone changes nothing.
    function seek(value, moved = true) {
      const next = finite(value) ? value : 0;
      if (!moved && Math.abs(next - time) <= 1e-9) return;
      start(next, last);
    }

    function result(realign = false) {
      return { time, mode, rate, holding, realign };
    }

    // The soundtrack advanced to `reading`: follow it from here.
    function lock(reading, now) {
      const offset = reading - time;
      mode = "sync";
      locked = true;
      holding = false;
      rate = 1;
      error = 0;
      outliers = outlierSign = 0;
      // A soundtrack no further behind than `realign` followed the last realignment (or never
      // needed one): a later lag, after another long stall, may be realigned again.
      if (offset >= -o.realign) realigned = false;
      if (offset >= 0) {
        if (offset > o.deadZone) counts.snaps++;
        time = reading;
      } else if (offset >= -o.snap) error = offset;
      else if (offset >= -o.realign) {
        holding = true;
        counts.holds++;
      } else return realignTo(now);
      return result();
    }

    function realignTo(now) {
      if (realigned) {
        // The soundtrack did not follow the last realignment: frames only until the next start
        // or seek.
        ignored = true;
        mode = "free";
        return result();
      }
      realigned = true;
      counts.realigns++;
      forget(now);
      wait(now);
      return result(true);
    }

    // One display frame at timestamp `now` (ms). `media`: the soundtrack's song time (s),
    // or NaN without a usable soundtrack (none, paused by the browser, ended); `ready`:
    // false while it seeks (buffering shows as readings that stop changing: a stall);
    // `loading`: the element has too little data to play yet (readyState below
    // HAVE_FUTURE_DATA), used only until the soundtrack first advances after start().
    // Returns { time, mode, rate, holding, realign }; realign asks the host to move the
    // soundtrack to `time`.
    function next(now, media, ready = true, loading = false) {
      const dt = finite(last) && finite(now) ? Math.max(0, now - last) / 1000 : 0;
      if (finite(now)) last = now;
      if (!finite(since)) since = now;
      const from = time;
      if (!finite(media) || ignored) {
        if (mode !== "free") forget(now);
        mode = "free";
        holding = false;
        rate = 1;
        error = 0;
        time += dt;
        return result();
      }
      let fresh = false, advanced = false;
      if (ready && media !== read) {
        // A new reading: the soundtrack's clock is alive.
        read = media;
        alive = now;
        // Behind where the soundtrack was heading: most likely a late reading (under load a
        // media element can hand out an old position). Used only once `confirm` + 1 agree.
        const behind = mode === "sync" && media < audio + Math.min((now - seen) / 1000, stallLimit()) - o.snap;
        late = behind ? late + 1 : 0;
        if (!behind || late > o.confirm) {
          fresh = true;
          const advance = media - audio;
          advanced = advance > 0;
          if (advanced && advance < 1) step += (Math.min(advance, o.maxStall) - step) / 4;
          audio = media;
          seen = now;
        }
      }
      if (mode === "sync" && (!ready || (now - alive) / 1000 > stallLimit())) wait(now, ready ? alive : now);
      if (mode !== "sync") {
        if (advanced) return lock(media, now);
        // A seeking soundtrack (a seek over the network can take seconds), or one still loading
        // before it first plays (WKWebView fetches the file on play()), is waited for: the time
        // towards giveUp counts from when it stopped seeking or loading.
        if (mode === "wait" && (!ready || (loading && !locked))) since = now;
        if (mode === "wait" && (now - since) / 1000 > o.giveUp) mode = "free";
        if (mode === "free") time += dt;
        return result();
      }

      const target = audio + Math.min((now - seen) / 1000, stallLimit());
      const gap = dt > o.maxGap;
      if (!holding) time += dt + (rate - 1) * Math.min(dt, o.maxGap);
      const offset = target - time;
      if (holding && offset >= 0) {
        // Caught up: continue from the soundtrack's time.
        holding = false;
        time = target;
        error = 0;
        rate = 1;
        return result();
      }
      const beyond = Math.abs(offset) > o.snap;
      if (fresh) {
        const sign = beyond ? Math.sign(offset) : 0;
        outliers = sign && sign === outlierSign ? outliers + 1 : sign ? 1 : 0;
        outlierSign = sign;
      }
      if (beyond && (gap || outliers >= o.confirm || late > o.confirm)) {
        outliers = outlierSign = late = 0;
        error = 0;
        rate = 1;
        if (offset > 0) {
          counts.snaps++;
          holding = false;
          time = target;
        } else if (-offset > o.realign) {
          time = Math.max(time, from);
          return realignTo(now);
        } else if (!holding) {
          holding = true;
          counts.holds++;
          time = from;
        }
      } else if (!beyond && !holding) {
        error += (offset - error) * Math.min(1, dt / o.filterTime);
        const excess = Math.abs(error) > o.deadZone ? (error - Math.sign(error) * o.deadZone) / o.slewTime : 0;
        rate = 1 + clamp(excess, -o.maxSlew, o.maxSlew);
      }
      time = Math.max(time, from);
      return result();
    }

    function state() {
      return { time, mode, rate, error, holding, step, stallLimit: stallLimit(), ignored, ...counts };
    }

    return { start, seek, next, state };
  }

  global.MVStudioPlaybackClock = Object.freeze({ create, DEFAULTS });
})(typeof window !== "undefined" ? window : globalThis);
