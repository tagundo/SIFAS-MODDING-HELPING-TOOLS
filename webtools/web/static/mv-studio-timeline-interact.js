/* Clip drag/trim, snapping and extrapolation times for the MV Studio timeline.

   attachDrag() is shared with editor plugins (the follow-camera rig lane): it
   turns pointer drags and Alt+arrow keys on one element into range previews
   and exactly one commit per gesture. The extrapolation port keeps the preview
   consistent with the game after a retime: the client recomputes these times
   at runtime (TrackAsset.UpdateDuration → CalculateExtrapolationTimes) while
   the preview reads the stored values. */
(function (global) {
  "use strict";

  const FRAME_RATE = 60;
  const FRAME = 1 / FRAME_RATE;
  const EPSILON = 1e-12;
  const UNBOUNDED = 3600;       // _set_timing needs a finite value ≤ 3600; the game ignores it anyway
  const finite = Number.isFinite;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  function snapFrame(time) {
    return Math.round(time * FRAME_RATE) / FRAME_RATE;
  }

  // Nearest target within `radius` px wins (unless Alt), then the frame grid always applies.
  function snapTime(time, options = {}) {
    const pps = finite(options.pixelsPerSecond) && options.pixelsPerSecond > 0 ? options.pixelsPerSecond : 1;
    const radius = finite(options.radius) ? options.radius : 6;
    let best = null, distance = Infinity;
    if (!options.alt) {
      for (const target of options.targets || []) {
        if (!finite(target)) continue;
        const gap = Math.abs(target - time) * pps;
        if (gap <= radius && gap < distance) { best = target; distance = gap; }
      }
    }
    return { time: snapFrame(best === null ? time : best), target: best, distance };
  }

  function bounded(bounds = {}) {
    const min = finite(bounds.min) ? bounds.min : 0;
    const max = finite(bounds.max) ? bounds.max : Infinity;
    const minLength = finite(bounds.minLength) && bounds.minLength > 0 ? bounds.minLength : FRAME;
    return { min, max, minLength };
  }

  // Moves [start, end) by delta seconds: either edge snaps (the nearer wins), the start
  // lands on the frame grid, the length is kept, and the range stays inside the bounds.
  function moveRange(range, delta, options = {}) {
    const { min, max } = bounded(options.bounds);
    const length = range.end - range.start;
    let start = range.start + delta;
    const head = snapTime(start, options), tail = snapTime(start + length, options);
    if (head.target !== null || tail.target !== null) {
      start = tail.target !== null && (head.target === null || tail.distance < head.distance) ? tail.target - length : head.target;
    }
    start = snapFrame(start);
    start = clamp(start, min, Math.max(min, max - length));
    return { start, end: start + length };
  }

  // Moves one edge ("start" or "end"); the other stays. Snapped and frame aligned.
  function resizeRange(range, delta, edge, options = {}) {
    const { min, max, minLength } = bounded(options.bounds);
    if (edge === "start") {
      const start = clamp(snapTime(range.start + delta, options).time, min, range.end - minLength);
      return { start, end: range.end };
    }
    const end = clamp(snapTime(range.end + delta, options).time, range.start + minLength, max);
    return { start: range.start, end };
  }

  // Alt+←/→: one frame, with Shift ten frames.
  function nudgeRange(range, frames, options = {}) {
    const { min, max } = bounded(options.bounds);
    const length = range.end - range.start;
    const start = clamp(snapFrame(range.start + frames * FRAME), min, Math.max(min, max - length));
    return { start, end: start + length };
  }

  /* Port of Unity Timeline's TrackAsset.CalculateExtrapolationTimes.
     clips: [{ id, start, duration, postMode }] → Map<id, { pre, post }> (post may be +Infinity). */
  function extrapolationTimes(clips) {
    const ordered = clips.slice().sort((first, second) => first.start - second.start);
    const result = new Map();
    if (!ordered.length) return result;
    const end = (clip) => clip.start + clip.duration;
    for (let i = 0; i < ordered.length; i++) {
      let post = Infinity;
      for (let j = 0; j < ordered.length; j++) {
        if (i === j) continue;
        const delta = ordered[j].start - end(ordered[i]);
        if (delta >= -EPSILON && delta < post) post = delta;
        if (ordered[j].start <= end(ordered[i]) && end(ordered[j]) > end(ordered[i])) post = 0;
      }
      result.set(ordered[i].id, { pre: 0, post: post <= EPSILON ? 0 : post });
    }
    result.get(ordered[0].id).pre = Math.max(0, ordered[0].start);
    for (let i = 1; i < ordered.length; i++) {
      let pre = 0, previous = -1;
      for (let j = 0; j < i; j++) {
        if (end(ordered[j]) > ordered[i].start) { previous = -1; pre = 0; break; }
        const gap = ordered[i].start - end(ordered[j]);
        if (previous < 0 || gap < pre) { pre = gap; previous = j; }
      }
      if (previous >= 0 && ordered[previous].postMode !== 0) pre = 0;
      result.get(ordered[i].id).pre = pre <= EPSILON ? 0 : pre;
    }
    return result;
  }

  // Stored extrapolation time as a number: JSON null (an exported Infinity) and the
  // editor's own 3600 stand for +Infinity; anything else that is not finite is unknown.
  function storedTime(value) {
    if (value === null) return Infinity;
    if (!finite(value)) return NaN;
    return value >= UNBOUNDED ? Infinity : value;
  }

  function clipsOf(track, overrides) {
    return (track.events || []).map((event) => {
      const override = overrides && overrides.get(event.id);
      const values = event.values || {};
      return { id: event.id, start: override && finite(override.start) ? override.start : event.start,
        duration: override && finite(override.duration) ? override.duration : event.duration,
        postMode: override && finite(override.postMode) ? override.postMode : Number(values.postExtrapolationMode) || 0 };
    });
  }

  const near = (first, second) => first === second || Math.abs(first - second) <= 1e-6;

  // Gate (spec §5.3): the port must reproduce every stored value of the track.
  function extrapolationGate(track) {
    const events = track && Array.isArray(track.events) ? track.events : [];
    if (!events.length) return false;
    for (const event of events) {
      const values = event && event.values;
      if (!values || !("preExtrapolationTime" in values) || !("postExtrapolationTime" in values)) return false;
      if (Number.isNaN(storedTime(values.preExtrapolationTime)) || Number.isNaN(storedTime(values.postExtrapolationTime))) return false;
    }
    const times = extrapolationTimes(clipsOf(track));
    return events.every((event) => {
      const computed = times.get(event.id);
      return computed && near(computed.pre, storedTime(event.values.preExtrapolationTime)) &&
        near(computed.post, storedTime(event.values.postExtrapolationTime));
    });
  }

  /* Writes that keep a gated track's stored times equal to the port after the
     timing (start/duration/postMode) of some events changes.
     overrides: Map<eventId, {start?, duration?, postMode?}> → [{ event, key, value }]. */
  function extrapolationChanges(track, overrides) {
    const times = extrapolationTimes(clipsOf(track, overrides));
    const changes = [];
    for (const event of track.events || []) {
      const computed = times.get(event.id);
      if (!computed) continue;
      for (const [key, value] of [["preExtrapolationTime", computed.pre], ["postExtrapolationTime", computed.post]]) {
        if (near(value, storedTime(event.values[key]))) continue;
        changes.push({ event, key, value: finite(value) ? value : UNBOUNDED });
      }
    }
    return changes;
  }

  const coarse = () => !!(global.matchMedia && global.matchMedia("(pointer: coarse)").matches);

  /* Drag/trim on one element.
     options: {
       getRange() → { start, end } | null       absolute seconds
       setRange(range, { phase: "preview"|"commit"|"cancel", mode: "move"|"start"|"end", key? })
       snapTargets() → [seconds]                 playhead, neighbouring edges, cuts …
       label                                     history label for the commit
       pixelsPerSecond() → number
       bounds() → { min, max, minLength }
       edges: { start = false, end = true }      which edges trim
       allowed() → { move?: false, resize?: false, reason? }
     }
     Returns detach(). */
  function attachDrag(element, options) {
    const edges = { start: false, end: true, ...(options.edges || {}) };
    let pending = null, drag = null, frame = 0, swallow = false;
    const pps = () => {
      const value = typeof options.pixelsPerSecond === "function" ? options.pixelsPerSecond() : options.pixelsPerSecond;
      return finite(value) && value > 0 ? value : 1;
    };
    const rules = () => ({ move: true, resize: true, ...(typeof options.allowed === "function" ? options.allowed() || {} : {}) });
    const bounds = () => typeof options.bounds === "function" ? options.bounds() : options.bounds;
    const targets = () => typeof options.snapTargets === "function" ? options.snapTargets() || [] : [];

    function compute(event) {
      const delta = (event.clientX - drag.x) / pps();
      const snap = { pixelsPerSecond: pps(), targets: drag.targets, alt: event.altKey, bounds: drag.bounds };
      return drag.mode === "move" ? moveRange(drag.range, delta, snap) : resizeRange(drag.range, delta, drag.mode, snap);
    }

    function flush() {
      frame = 0;
      if (drag && drag.next) options.setRange(drag.next, { phase: "preview", mode: drag.mode });
    }

    function finish(phase) {
      if (frame) { cancelAnimationFrame(frame); frame = 0; }
      const current = drag;
      drag = null;
      element.classList.remove("mv-dragging");
      global.removeEventListener("keydown", escape, true);
      if (!current) return;
      swallow = true;
      setTimeout(() => { swallow = false; }, 0);
      if (phase === "commit" && current.next) options.setRange(current.next, { phase, mode: current.mode });
      else options.setRange(current.range, { phase: "cancel", mode: current.mode });
    }

    function escape(event) {
      if (event.key !== "Escape" || !drag) return;
      event.preventDefault();
      event.stopPropagation();
      finish("cancel");
    }

    function down(event) {
      if (event.button !== 0 || drag || !event.isPrimary) return;
      const range = options.getRange();
      if (!range) return;
      const allowed = rules();
      const box = element.getBoundingClientRect();
      const zone = event.pointerType === "touch" || coarse() ? 12 : 6;
      let mode = null;
      if (edges.end && allowed.resize !== false && box.right - event.clientX <= zone && box.width > zone) mode = "end";
      else if (edges.start && allowed.resize !== false && event.clientX - box.left <= zone && box.width > zone) mode = "start";
      else if (allowed.move !== false) mode = "move";
      pending = mode ? { id: event.pointerId, x: event.clientX, mode, range: { start: range.start, end: range.end } } : null;
    }

    function move(event) {
      if (drag && event.pointerId === drag.id) {
        drag.next = compute(event);
        if (!frame) frame = requestAnimationFrame(flush);
        return;
      }
      if (!pending || event.pointerId !== pending.id || Math.abs(event.clientX - pending.x) <= 3) return;
      drag = { ...pending, targets: targets(), bounds: bounds(), next: null };
      pending = null;
      try { element.setPointerCapture(event.pointerId); } catch (_) {}
      element.classList.add("mv-dragging");
      global.addEventListener("keydown", escape, true);
      drag.next = compute(event);
      if (!frame) frame = requestAnimationFrame(flush);
    }

    function up(event) {
      if (pending && event.pointerId === pending.id) pending = null;
      if (!drag || event.pointerId !== drag.id) return;
      drag.next = compute(event);
      finish("commit");
    }

    function cancel(event) {
      if (pending && event.pointerId === pending.id) pending = null;
      if (drag && event.pointerId === drag.id) finish("cancel");
    }

    function click(event) {
      if (!swallow) return;
      swallow = false;
      event.preventDefault();
      event.stopImmediatePropagation();
    }

    function key(event) {
      if (!event.altKey || event.ctrlKey || event.metaKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
      const range = options.getRange();
      if (!range || rules().move === false) return;
      event.preventDefault();
      event.stopPropagation();
      const frames = (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 10 : 1);
      const next = nudgeRange(range, frames, { bounds: bounds() });
      if (next.start !== range.start) options.setRange(next, { phase: "commit", mode: "move", key: true });
    }

    element.addEventListener("pointerdown", down);
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerup", up);
    element.addEventListener("pointercancel", cancel);
    element.addEventListener("lostpointercapture", cancel);
    element.addEventListener("click", click, true);
    element.addEventListener("keydown", key);
    return function detach() {
      if (drag) finish("cancel");
      for (const [type, listener, capture] of [["pointerdown", down], ["pointermove", move], ["pointerup", up],
        ["pointercancel", cancel], ["lostpointercapture", cancel], ["click", click, true], ["keydown", key]]) {
        element.removeEventListener(type, listener, !!capture);
      }
    };
  }

  global.MVStudioTimelineInteract = Object.freeze({
    FRAME_RATE, FRAME, UNBOUNDED, snapFrame, snapTime, moveRange, resizeRange, nudgeRange,
    extrapolationTimes, extrapolationGate, extrapolationChanges, storedTime, attachDrag,
  });
})(typeof window !== "undefined" ? window : globalThis);
