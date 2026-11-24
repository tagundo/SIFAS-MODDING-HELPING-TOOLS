/* MV Studio camera editor (MVStudioCameraKeys): Unity/Blender-style keys on the
   MainCamera shots, baked into each shot's dense 60 Hz samples.

   Why an edit used to "snap back": a shot stores a dense sample every 1/60 s and
   the inspector edited only one of them. Here an edit is a key whose effect spans
   the shot (one key = a constant change over the whole shot), and the shot's
   values.keyframes are re-derived from the original samples:

     project.editor.camera.shots[eventId] = {
       mode: "offset" | "keys",      // offset: deltas over the original motion; keys: replace it
       space: "view" | "world",      // offset deltas along the view (truck/pedestal/dolly) or world X/Y/Z
       keys: [{ frame,               // integer index on the shot's own sample grid
                values: { x, y, z, pan, tilt, roll, fov },
                interp: "constant" | "linear" | "bezier",
                handle: "auto-clamped" | "auto" | "flat" | "free",
                handles?: { [channel]: { in: [dFrames, dValue], out: [dFrames, dValue] } } }] }

   The bake keeps the original sample count and time floats (the native exporter's
   rule), keeps the quaternions continuous, and gives back the original samples bit
   for bit when nothing is edited. History stores only these records; the bake
   runs again after every apply/undo/redo (projectChanged). Registered layers (the
   follow camera, MVStudioCameraKeys.registerLayer) are applied after the keys.

   An unedited project is never touched: nothing is written, and project.editor is
   not created, until the first camera edit. */
(function (global) {
  "use strict";

  const M = global.MVStudioCameraMath;
  const FRAME_RATE = 60;
  const CHANNELS = M.CHANNELS;
  const RAW_FIELDS = ["m_Position", "m_Rotation", "m_EulerAngles"];
  const USER_TRACK = "camera-editor";
  const finite = Number.isFinite;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const clone = (value) => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  const vector = (value, size) => Array.isArray(value) && value.length >= size && value.slice(0, size).every(finite);
  const clampFov = (value) => clamp(value, 1, 170);
  const zeros = () => Object.fromEntries(CHANNELS.map((channel) => [channel, 0]));

  // ---- per-editor state (one ctx per MV Studio mount; tests make several) -----------------
  const states = new WeakMap();
  function stateOf(ctx) {
    let state = states.get(ctx);
    if (!state) {
      state = { selected: null, channels: ["x"], autoKey: false, space: "view", pending: null, controller: null, events: undefined,
        scene: null, unsubscribe: null, panel: null, curves: null, differs: new WeakMap(), lastShot: null, helper: false };
      states.set(ctx, state);
    }
    return state;
  }

  const t = (ctx, label) => typeof ctx.t === "function" ? ctx.t(label) : label;
  const format = (ctx, label, values) => typeof ctx.format === "function" ? ctx.format(label, values)
    : label.replace(/\{(\w+)\}/g, (match, key) => key in values ? String(values[key]) : match);

  function formatTime(seconds) {
    const centiseconds = Math.max(0, Math.round(seconds * 100));
    const minutes = Math.floor(centiseconds / 6000), remainder = centiseconds % 6000;
    return `${minutes}:${String(Math.floor(remainder / 100)).padStart(2, "0")}.${String(remainder % 100).padStart(2, "0")}`;
  }

  // ---- layers (follow camera and other derived motion) --------------------------------------
  const layers = [];
  function registerLayer(layer) {
    if (!layer || typeof layer.id !== "string" || typeof layer.apply !== "function") throw new TypeError("A camera layer needs an id and apply().");
    const index = layers.findIndex((item) => item.id === layer.id);
    if (index >= 0) layers.splice(index, 1);
    layers.push(layer);
    layers.sort((a, b) => (finite(a.order) ? a.order : 0) - (finite(b.order) ? b.order : 0) || a.id.localeCompare(b.id));
    return () => unregisterLayer(layer.id);
  }
  function unregisterLayer(id) {
    const index = layers.findIndex((item) => item.id === id);
    if (index >= 0) layers.splice(index, 1);
  }
  function affecting(ctx, shot) {
    return layers.filter((layer) => {
      try { return typeof layer.affects !== "function" || layer.affects(ctx, shot) === true; } catch (error) { console.error(error); return false; }
    });
  }

  // ---- shots ----------------------------------------------------------------------------------
  // The camera tracks the scene renders as the main camera (renderTracks): binding absent or
  // matching MainCamera, not LiveCameraOffsetTrack. Split SubCamera tracks are out of scope.
  function mainTrack(track) {
    return !!track && track.kind === "camera" && track.nativeClass !== "LiveCameraOffsetTrack" && !track.muted &&
      (!track.binding || /MainCamera/i.test(track.binding)) && Array.isArray(track.events);
  }

  function mainTracks(project) {
    return project && Array.isArray(project.tracks) ? project.tracks.filter(mainTrack) : [];
  }

  // [{ track, event }] of every main-camera shot, by start.
  function mainCameraShots(ctx) {
    const list = [];
    for (const track of mainTracks(ctx.project())) for (const event of track.events) if (event) list.push({ track, event });
    return list.sort((a, b) => a.event.start - b.event.start);
  }

  function validFrames(frames) {
    return Array.isArray(frames) && frames.length > 0 &&
      frames.every((frame) => frame && finite(frame.time) && vector(frame.position, 3) && vector(frame.rotation, 4));
  }

  // A static shot (position/rotation/fov values, non-native projects) on a 60 Hz grid.
  function staticGrid(values, duration) {
    const count = Math.max(2, Math.ceil(Math.max(0, duration) * FRAME_RATE - 1e-6) + 1);
    return Array.from({ length: count }, (_, index) => ({ time: Math.min(index / FRAME_RATE, duration),
      position: values.position.slice(0, 3), rotation: values.rotation.slice(0, 4), fov: finite(values.fov) ? values.fov : null }));
  }

  const sameNumberArray = (a, b) => a === b || (Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((value, index) => value === b[index]));

  function sameFrames(a, b) {
    if (a === b) return true;
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    for (let index = 0; index < a.length; index++) {
      const x = a[index], y = b[index];
      if (!x || !y || x.time !== y.time || x.fov !== y.fov || !sameNumberArray(x.position, y.position) || !sameNumberArray(x.rotation, y.rotation)) return false;
      const keys = Object.keys(x);
      if (keys.length !== Object.keys(y).length) return false;
    }
    return true;
  }

  function recordOf(ctx, eventId) {
    const editor = ctx.editor(false);
    const shots = editor && editor.camera && editor.camera.shots;
    return shots && Object.prototype.hasOwnProperty.call(shots, eventId) ? shots[eventId] : undefined;
  }

  // A stored record, checked and cleaned against the shot's sample count.
  function normalizeRecord(raw, count) {
    if (!raw || typeof raw !== "object" || !["offset", "keys"].includes(raw.mode)) return null;
    const byFrame = new Map();
    for (const key of Array.isArray(raw.keys) ? raw.keys : []) {
      if (!key || !Number.isInteger(key.frame) || !key.values || typeof key.values !== "object") continue;
      const values = {};
      for (const channel of CHANNELS) values[channel] = finite(key.values[channel]) ? key.values[channel] : (raw.mode === "keys" && channel === "fov" ? 30 : 0);
      const clean = { frame: clamp(key.frame, 0, Math.max(0, count - 1)), values,
        interp: M.INTERPOLATIONS.includes(key.interp) ? key.interp : "bezier",
        handle: M.HANDLES.includes(key.handle) ? key.handle : "auto-clamped" };
      if (clean.handle === "free" && key.handles && typeof key.handles === "object") {
        const handles = {};
        for (const channel of CHANNELS) {
          const pair = key.handles[channel];
          if (pair && vector(pair.in, 2) && vector(pair.out, 2)) handles[channel] = { in: pair.in.slice(0, 2), out: pair.out.slice(0, 2) };
        }
        clean.handles = handles;
      }
      byFrame.set(clean.frame, clean);
    }
    return { mode: raw.mode, space: raw.space === "world" ? "world" : "view", keys: [...byFrame.values()].sort((a, b) => a.frame - b.frame) };
  }

  // Everything the editor needs about one shot; null when it is not a main-camera shot.
  function shotInfo(ctx, track, event, time) {
    if (!mainTrack(track) || !event) return null;
    const project = ctx.project();
    const history = ctx.history;
    const original = history && history.originals ? history.originals.get(event.id) : undefined;
    const user = original === null;
    // Dense samples: the original ones (the event's are derived by the bake). A static pose
    // (non-native projects) is never written by the bake, so the event's own values are its source.
    const current = event.values || {};
    const values = original && original.values ? original.values : current;
    let source = null, staticSource = false;
    if (validFrames(values.keyframes)) source = values.keyframes;
    else if (!user && vector(current.position, 3) && vector(current.rotation, 4) && project && project.nativeTimeline !== true) {
      source = staticGrid(current, event.duration);
      staticSource = true;
    }
    const native = project && project.nativeTimeline === true;
    let editable = !!source && source.length >= 2 && track.editable !== false && event.editable !== false;
    let reason = "";
    if (editable && native && !(Array.isArray(event.editableValues) && event.editableValues.includes("keyframes"))) {
      editable = false;
      reason = "The camera samples of this shot cannot be exported.";
    }
    const lengthChanged = !!(native && original && original.duration !== event.duration);
    if (editable && lengthChanged) {
      editable = false;
      reason = "Restore this shot's original length to edit its camera.";
    }
    const count = source ? source.length : 0;
    const shots = mainCameraShots(ctx);
    const info = { track, event, source, count, user, native, staticSource, editable, reason, lengthChanged,
      record: source ? normalizeRecord(recordOf(ctx, event.id), count) : null,
      lens: M.nativeLens(track), index: shots.findIndex((item) => item.event === event), total: shots.length,
      fallbackFov: finite(current.fov) ? current.fov : finite(values.fov) ? values.fov : 30 };
    if (finite(time) && source) info.frame = frameAt(info, time);
    return info;
  }

  function findShot(ctx, eventId, time) {
    for (const track of mainTracks(ctx.project())) {
      const event = track.events.find((item) => item && item.id === eventId);
      if (event) return shotInfo(ctx, track, event, time);
    }
    return null;
  }

  // The sample nearest `time` (absolute seconds).
  function frameAt(shot, time) {
    const local = clamp(time - shot.event.start, 0, Math.max(0, shot.event.duration));
    const frames = shot.source;
    let lower = 0, upper = frames.length - 1;
    while (upper - lower > 1) {
      const mid = (lower + upper) >> 1;
      if (frames[mid].time <= local) lower = mid; else upper = mid;
    }
    return Math.abs(frames[upper].time - local) < Math.abs(local - frames[lower].time) ? upper : lower;
  }

  const frameTime = (shot, frame) => shot.event.start + shot.source[clamp(frame, 0, shot.count - 1)].time;

  // activeCameraEvent of the scene: latest-start active clip, else the Hold neighbours.
  function activeCameraEvent(track, time) {
    let active = null;
    for (const event of track.events) {
      if (event.start <= time && time <= event.start + event.duration && (!active || event.start >= active.start)) active = event;
    }
    if (active) return active;
    let previous = null, next = null;
    for (const event of track.events) {
      const values = event.values || {}, end = event.start + event.duration;
      if (time > end && values.postExtrapolationMode === 1 && time <= end + values.postExtrapolationTime && (!previous || event.start > previous.start)) previous = event;
      if (time < event.start && values.preExtrapolationMode === 1 && time >= event.start - values.preExtrapolationTime && (!next || event.start < next.start)) next = event;
    }
    return previous || next;
  }

  // The shot the game camera shows at `time` (the last main-camera track wins, as in the scene).
  function playheadShot(ctx, time = ctx.time()) {
    const project = ctx.project();
    let found = null, ended = null;
    for (const track of mainTracks(project)) {
      const event = activeCameraEvent(track, time);
      if (event) { found = { track, event }; continue; }
      if (project.source && project.source.kind === "game") {
        for (const item of track.events) {
          if (time > item.start + item.duration && (!ended || item.start + item.duration > ended.event.start + ended.event.duration)) ended = { track, event: item };
        }
      }
    }
    found = found || ended;
    return found ? shotInfo(ctx, found.track, found.event, time) : null;
  }

  // ---- poses and the bake ---------------------------------------------------------------------
  // Curve values at frame f: deltas (offset) or absolute values (keys). With no keys an offset
  // record is zero and a keys record follows the source.
  function channelValues(shot, record, frame) {
    if (record && record.keys.length) return M.evaluate(record.keys, frame);
    if (!record || record.mode === "offset") return zeros();
    return absoluteOf(sourcePose(shot, frame));
  }

  function sourcePose(shot, frame) {
    const sample = shot.source[frame];
    return { position: sample.position, rotation: sample.rotation, fov: finite(sample.fov) ? sample.fov : null };
  }

  function absoluteOf(pose, near) {
    const euler = M.quaternionToEulerZXY(pose.rotation, near);
    return { x: pose.position[0], y: pose.position[1], z: pose.position[2], pan: euler.pan, tilt: euler.tilt, roll: euler.roll,
      fov: finite(pose.fov) ? pose.fov : null };
  }

  // The keyed pose at frame i, before layers. Untouched channels keep the source arrays
  // (by reference) so the output can copy them bit for bit.
  function basePose(shot, record, frame) {
    const sample = shot.source[frame];
    const pose = { position: sample.position, rotation: sample.rotation, fov: sample.fov === undefined ? null : sample.fov };
    if (!record || !record.keys.length) return pose;
    const value = M.evaluate(record.keys, frame);
    if (record.mode === "keys") {
      return { position: [value.x, value.y, value.z], rotation: M.normalize(M.eulerZXYToQuaternion(value)), fov: clampFov(value.fov) };
    }
    const q = M.normalize(sample.rotation);
    if (value.x || value.y || value.z) {
      const delta = record.space === "world" ? [value.x, value.y, value.z] : M.rotateVector(q, [-value.x, value.y, -value.z]);
      pose.position = [sample.position[0] + delta[0], sample.position[1] + delta[1], sample.position[2] + delta[2]];
    }
    if (value.pan || value.tilt || value.roll) pose.rotation = M.normalize(M.multiply(q, M.eulerZXYToQuaternion(value)));
    if (value.fov) pose.fov = clampFov((finite(sample.fov) ? sample.fov : shot.fallbackFov) + value.fov);
    return pose;
  }

  // The baked samples of a shot, or { restore: true } when nothing applies to it.
  function bakeShot(ctx, shot) {
    const record = shot.record;
    const active = affecting(ctx, shot);
    if ((!record || !record.keys.length) && !active.length) return { restore: true };
    const frames = shot.source.map((sample, index) => {
      const pose = basePose(shot, record, index);
      return { t: shot.event.start + sample.time, position: pose.position, rotation: pose.rotation, fov: pose.fov };
    });
    for (const layer of active) {
      try { layer.apply(ctx, shot, frames); } catch (error) { console.error(`MV Studio camera layer ${layer.id}`, error); }
    }
    const keyframes = [];
    let previous = null;
    frames.forEach((frame, index) => {
      const sample = shot.source[index];
      const position = vector(frame.position, 3) ? frame.position.slice(0, 3) : sample.position.slice(0, 3);
      let rotation = vector(frame.rotation, 4) ? frame.rotation : sample.rotation;
      rotation = rotation === sample.rotation ? rotation.slice(0, 4) : M.normalize(rotation);
      // Same hemisphere as the previous sample: the writer's Euler and the game's lerp stay continuous.
      if (previous && M.dot(previous, rotation) < 0) rotation = rotation.map((value) => -value);
      previous = rotation;
      let fov = frame.fov === undefined ? null : frame.fov;
      if (fov !== sample.fov && finite(fov)) fov = clampFov(fov);
      else if (fov !== sample.fov) fov = sample.fov === undefined ? null : sample.fov;
      keyframes.push({ time: sample.time, position, rotation, fov });
    });
    return { keyframes };
  }

  // Writes a bake outside history (spec §7.5); true when the shot's samples changed.
  function writeBake(ctx, shot, result) {
    const event = shot.event;
    const values = event.values || (event.values = {});
    if (result.restore) {
      if (shot.user) return false;
      const original = ctx.history.originals.get(event.id);
      if (!original || !original.values) return false;   // never written: nothing to restore
      const keyframes = original.values.keyframes;
      if (Array.isArray(keyframes)) {
        if (sameFrames(values.keyframes, keyframes)) return false;
        values.keyframes = clone(keyframes);
      } else {
        if (!Object.prototype.hasOwnProperty.call(values, "keyframes")) return false;
        delete values.keyframes;
      }
      return true;
    }
    if (sameFrames(values.keyframes, result.keyframes)) return false;
    if (!shot.user) ctx.history.originals.ensure(event.id);
    values.keyframes = result.keyframes;
    return true;
  }

  // Whether a shot's samples differ from its original ones (cached per samples array).
  function differs(ctx, event) {
    const original = ctx.history && ctx.history.originals ? ctx.history.originals.get(event.id) : undefined;
    if (original === undefined) return false;
    if (original === null) return !!recordOf(ctx, event.id);
    const current = event.values && event.values.keyframes, before = original.values && original.values.keyframes;
    if (!Array.isArray(current) || !Array.isArray(before)) return Array.isArray(current) !== Array.isArray(before);
    const cache = stateOf(ctx).differs, hit = cache.get(current);
    if (hit && hit.before === before) return hit.result;
    const result = !sameFrames(current, before);
    cache.set(current, { before, result });
    return result;
  }

  // Shots a bake must visit: those with a record, a layer, or samples to restore.
  function candidates(ctx, events) {
    const list = [];
    for (const { track, event } of mainCameraShots(ctx)) {
      if (events && !events.includes(event.id)) continue;
      const shot = shotInfo(ctx, track, event);
      if (!shot || !shot.source || (shot.lengthChanged && !differs(ctx, event))) continue;
      if (shot.record || differs(ctx, event) || (layers.length && affecting(ctx, shot).length)) list.push(shot);
    }
    return list;
  }

  function bakeNow(ctx, events) {
    const changed = new Set();
    for (const shot of candidates(ctx, events)) {
      if (writeBake(ctx, shot, bakeShot(ctx, shot))) changed.add(shot.track.id);
    }
    for (const id of changed) ctx.refreshLane(id);
    if (changed.size) ctx.seek(ctx.time(), { audio: false });
    return changed.size > 0;
  }

  function mergeEvents(a, b) {
    if (a === undefined || b === undefined) return undefined;
    return [...new Set([...a, ...b])];
  }

  // Rebakes shots (all when events is undefined). Keys-only bakes run now; a bake with a
  // layer that prepares data (prepare()) awaits it and is cancelled by a newer one.
  function requestBake(ctx, { events, reason } = {}) {
    if (!ctx.project()) return Promise.resolve();
    const state = stateOf(ctx);
    const list = candidates(ctx, events);
    const preparing = layers.filter((layer) => typeof layer.prepare === "function" && list.some((shot) => affecting(ctx, shot).includes(layer)));
    if (!preparing.length) {
      bakeNow(ctx, events);
      renderPanel(ctx);
      return state.pending || Promise.resolve();
    }
    const scope = state.controller ? mergeEvents(state.events, events) : events;
    if (state.controller) state.controller.abort();
    const controller = new AbortController();
    state.controller = controller;
    state.events = scope;
    const run = (async () => {
      for (const layer of preparing) {
        const shots = candidates(ctx, scope).filter((shot) => affecting(ctx, shot).includes(layer));
        await layer.prepare(ctx, shots, controller.signal, { reason });
        if (controller.signal.aborted) return;
      }
      bakeNow(ctx, scope);
      renderPanel(ctx);
    })();
    const settled = run.catch((error) => {
      if (error && error.name === "AbortError") return;
      console.error(error);
      ctx.report(t(ctx, "The camera could not be baked."), true);
    }).finally(() => {
      if (state.controller === controller) { state.controller = null; state.pending = null; state.events = undefined; }
    });
    state.pending = settled;
    return settled;
  }

  // ---- history commands -------------------------------------------------------------------------
  function cleanRecord(record) {
    return { mode: record.mode, space: record.space, keys: record.keys.slice().sort((a, b) => a.frame - b.frame).map((key) => {
      const item = { frame: key.frame, values: Object.fromEntries(CHANNELS.map((channel) => [channel, key.values[channel]])),
        interp: key.interp, handle: key.handle };
      if (key.handle === "free" && key.handles) item.handles = clone(key.handles);
      return item;
    }) };
  }

  function commit(ctx, shot, record, label, detail) {
    if (ctx.locked() || !ctx.history) return false;
    const editor = ctx.editor(false);
    const changes = [];
    if (!editor || !editor.camera || editor.camera.version !== 1) changes.push({ target: { kind: "editor" }, path: ["camera", "version"], after: 1 });
    changes.push({ target: { kind: "editor" }, path: ["camera", "shots", shot.event.id], after: record ? cleanRecord(record) : undefined });
    return ctx.history.apply({ label, detail: detail || shot.event.label || "", changes });
  }

  function emptyRecord(ctx) {
    return { mode: "offset", space: stateOf(ctx).space, keys: [] };
  }

  function upsertKey(record, frame, values, template) {
    const existing = record.keys.find((key) => key.frame === frame);
    if (existing) { existing.values = values; return existing; }
    const key = { frame, values, interp: template ? template.interp : "bezier", handle: template ? template.handle : "auto-clamped" };
    record.keys.push(key);
    record.keys.sort((a, b) => a.frame - b.frame);
    return key;
  }

  function select(ctx, shot, frame) {
    stateOf(ctx).selected = frame === null || frame === undefined ? null : { event: shot.event.id, frame };
  }

  function selectedKey(ctx, shot) {
    const selected = stateOf(ctx).selected;
    if (!shot || !shot.record || !selected || selected.event !== shot.event.id) return null;
    return shot.record.keys.find((key) => key.frame === selected.frame) || null;
  }

  function requireShot(ctx, shot) {
    if (!shot) { ctx.report(t(ctx, "No camera shot at the playhead."), true); return null; }
    if (!shot.editable) { ctx.report(t(ctx, shot.reason || "This camera shot cannot be edited."), true); return null; }
    return shot;
  }

  // Deltas at frame f that give the absolute target pose (position, euler, fov) from the
  // source sample, for the channel groups in `groups`; the others keep `current`.
  function deltasFor(shot, record, frame, target, groups, current) {
    const sample = shot.source[frame], q = M.normalize(sample.rotation);
    const values = { ...current };
    if (groups.has("position")) {
      const world = [target.x - sample.position[0], target.y - sample.position[1], target.z - sample.position[2]];
      if (record.space === "world") Object.assign(values, { x: world[0], y: world[1], z: world[2] });
      else {
        const local = M.rotateVector(M.conjugate(q), world);
        Object.assign(values, { x: -local[0], y: local[1], z: -local[2] });
      }
    }
    if (groups.has("rotation")) {
      const goal = target.rotation || M.eulerZXYToQuaternion(target);
      const delta = M.multiply(M.conjugate(q), M.normalize(goal));
      Object.assign(values, M.quaternionToEulerZXY(delta, { pan: current.pan, tilt: current.tilt, roll: current.roll }));
    }
    if (groups.has("fov") && finite(target.fov)) values.fov = target.fov - (finite(sample.fov) ? sample.fov : shot.fallbackFov);
    return values;
  }

  const groupOf = (channel) => M.POSITION.includes(channel) ? "position" : M.ROTATION.includes(channel) ? "rotation" : "fov";

  // The curve view follows the edited channel: added to the visible ones of the same unit,
  // or shown alone when the others are in another unit.
  function showChannel(ctx, channel) {
    if (!CHANNELS.includes(channel)) return;
    const state = stateOf(ctx);
    const unit = (name) => groupOf(name) === "position" ? "m" : "deg";
    state.channels = state.channels.every((name) => unit(name) === unit(channel))
      ? CHANNELS.filter((name) => name === channel || state.channels.includes(name)) : [channel];
  }

  // The at-playhead fields: row "offset" (deltas) or "absolute" (the keyed pose). Updates the key
  // at the playhead frame, or inserts one holding the current curve values (auto-key).
  function setChannels(ctx, row, patch, { time } = {}) {
    const shot = requireShot(ctx, playheadShot(ctx, finite(time) ? time : ctx.time()));
    if (!shot) return false;
    const frame = shot.frame;
    const record = shot.record ? clone(shot.record) : emptyRecord(ctx);
    const current = channelValues(shot, record, frame);
    let values;
    if (row === "absolute" && record.mode === "offset") {
      const pose = basePose(shot, record, frame);
      const absolute = absoluteOf(pose, M.quaternionToEulerZXY(shot.source[frame].rotation));
      if (!finite(absolute.fov)) absolute.fov = shot.fallbackFov;
      const groups = new Set(Object.keys(patch).map(groupOf));
      values = deltasFor(shot, record, frame, { ...absolute, ...patch }, groups, current);
    } else values = { ...current, ...patch };
    if (record.mode === "keys" && finite(values.fov)) values.fov = clampFov(values.fov);
    upsertKey(record, frame, values);
    const channel = Object.keys(patch)[0];
    showChannel(ctx, channel);
    select(ctx, shot, frame);
    const changed = commit(ctx, shot, record, "Edit camera key", channel);
    renderPanel(ctx);
    return changed;
  }

  // The free (orbit) view as a rig pose at the shot's frame: LiveCameraOffset is removed along
  // the rig's up and the FOV is the authored one (before the aspect correction).
  function viewTarget(ctx, shot, frame) {
    const scene = ctx.scene();
    const view = scene && typeof scene.getViewPose === "function" ? scene.getViewPose() : null;
    if (!view) return null;
    const rotation = M.threeToUnityQuaternion(view.quaternion);
    let position = M.threeToUnityPosition(view.position);
    const offset = typeof scene.cameraOffsetAt === "function" ? scene.cameraOffsetAt(frameTime(shot, frame), shot.track.binding) : 0;
    if (finite(offset) && offset) {
      const up = M.rotateVector(M.normalize(rotation), [0, offset, 0]);
      position = position.map((value, index) => value - up[index]);
    }
    const fov = shot.lens ? view.fov * M.aspectCorrection(view.aspect) : view.fov;
    return { mode: view.mode, position, rotation, fov };
  }

  function keyView(ctx, { auto = false } = {}) {
    if (ctx.locked()) return false;
    const found = playheadShot(ctx);
    if (auto && (!found || !found.editable)) return false;
    const shot = requireShot(ctx, found);
    if (!shot) return false;
    const frame = shot.frame;
    const view = viewTarget(ctx, shot, frame);
    if (!view) return false;
    if (view.mode !== "orbit") {
      if (!auto) ctx.report(t(ctx, "Switch the preview camera to Free camera to key the view."), true);
      return false;
    }
    const record = shot.record ? clone(shot.record) : emptyRecord(ctx);
    const current = channelValues(shot, record, frame);
    let values;
    if (record.mode === "keys") {
      const euler = M.quaternionToEulerZXY(view.rotation, { pan: current.pan, tilt: current.tilt, roll: current.roll });
      values = { x: view.position[0], y: view.position[1], z: view.position[2], ...euler, fov: clampFov(view.fov) };
    } else {
      values = deltasFor(shot, record, frame, { x: view.position[0], y: view.position[1], z: view.position[2], rotation: view.rotation, fov: view.fov },
        new Set(["position", "rotation", "fov"]), current);
    }
    upsertKey(record, frame, values);
    select(ctx, shot, frame);
    const changed = commit(ctx, shot, record, "Key current view");
    // The playhead lands on the keyed frame, where the game camera now shows the view.
    ctx.seek(frameTime(shot, frame), { audio: false });
    renderPanel(ctx);
    return changed;
  }

  function addKey(ctx) {
    const shot = requireShot(ctx, playheadShot(ctx));
    if (!shot) return false;
    const record = shot.record ? clone(shot.record) : emptyRecord(ctx);
    const frame = shot.frame;
    let changed = false;
    select(ctx, shot, frame);
    if (!record.keys.some((key) => key.frame === frame)) {
      upsertKey(record, frame, channelValues(shot, record, frame));
      changed = commit(ctx, shot, record, "Add camera key");
    } else ctx.refreshLane(shot.track.id);
    renderPanel(ctx);
    return changed;
  }

  function targetKey(ctx) {
    const shot = playheadShot(ctx);
    const selected = stateOf(ctx).selected;
    const owner = selected && (shot && shot.event.id === selected.event ? shot : findShot(ctx, selected.event, ctx.time()));
    const key = owner && selectedKey(ctx, owner);
    if (key) return { shot: owner, key };
    const atPlayhead = shot && shot.record && shot.record.keys.find((item) => item.frame === shot.frame);
    return atPlayhead ? { shot, key: atPlayhead } : null;
  }

  function deleteKey(ctx) {
    const found = targetKey(ctx);
    if (!found || !found.shot.editable) return false;
    const record = clone(found.shot.record);
    record.keys = record.keys.filter((key) => key.frame !== found.key.frame);
    stateOf(ctx).selected = null;
    const changed = commit(ctx, found.shot, record, "Delete camera key");
    renderPanel(ctx);
    return changed;
  }

  function duplicateKey(ctx) {
    const found = targetKey(ctx);
    const shot = playheadShot(ctx);
    if (!found || !shot || shot.event !== found.shot.event || !shot.editable || shot.frame === found.key.frame) return false;
    const record = clone(shot.record);
    const source = record.keys.find((key) => key.frame === found.key.frame);
    record.keys = record.keys.filter((key) => key.frame !== shot.frame);
    record.keys.push({ ...clone(source), frame: shot.frame });
    record.keys.sort((a, b) => a.frame - b.frame);
    select(ctx, shot, shot.frame);
    const changed = commit(ctx, shot, record, "Duplicate camera key");
    renderPanel(ctx);
    return changed;
  }

  // Previous (-1) / next (+1) key of the shot under the playhead.
  function stepKey(ctx, direction) {
    const shot = playheadShot(ctx);
    if (!shot || !shot.record || !shot.record.keys.length) return false;
    const local = ctx.time() - shot.event.start;
    const keys = shot.record.keys;
    const key = direction < 0 ? keys.slice().reverse().find((item) => shot.source[item.frame].time < local - 1e-9)
      : keys.find((item) => shot.source[item.frame].time > local + 1e-9);
    if (!key) return false;
    select(ctx, shot, key.frame);
    ctx.seek(frameTime(shot, key.frame), { audio: false });
    ctx.refreshLane(shot.track.id);
    renderPanel(ctx);
    return true;
  }

  // Moves a key to another frame of its shot, between its neighbours.
  function moveKey(ctx, eventId, from, to) {
    const shot = findShot(ctx, eventId, ctx.time());
    if (!shot || !shot.editable || !shot.record) return false;
    const record = clone(shot.record);
    const index = record.keys.findIndex((key) => key.frame === from);
    if (index < 0) return false;
    const low = index > 0 ? record.keys[index - 1].frame + 1 : 0;
    const high = index + 1 < record.keys.length ? record.keys[index + 1].frame - 1 : shot.count - 1;
    const frame = clamp(Math.round(to), low, high);
    select(ctx, shot, frame);
    if (frame === from) return false;
    record.keys[index].frame = frame;
    const changed = commit(ctx, shot, record, "Move camera key");
    renderPanel(ctx);
    return changed;
  }

  // One key's values (curve view drag): a channel value and optionally its frame.
  function setKeyValue(ctx, eventId, from, { frame, channel, value }) {
    const shot = findShot(ctx, eventId, ctx.time());
    if (!shot || !shot.editable || !shot.record) return false;
    const record = clone(shot.record);
    const index = record.keys.findIndex((key) => key.frame === from);
    if (index < 0) return false;
    const key = record.keys[index];
    if (finite(frame)) {
      const low = index > 0 ? record.keys[index - 1].frame + 1 : 0;
      const high = index + 1 < record.keys.length ? record.keys[index + 1].frame - 1 : shot.count - 1;
      key.frame = clamp(Math.round(frame), low, high);
    }
    if (channel && finite(value)) key.values[channel] = record.mode === "keys" && channel === "fov" ? clampFov(value) : value;
    select(ctx, shot, key.frame);
    commit(ctx, shot, record, "Move camera key", channel);
    return key.frame;
  }

  // Bezier handles of one key (curve view): the key becomes "free"; every channel keeps the
  // handles it had, the dragged side takes `handle`.
  function setHandle(ctx, eventId, frame, channel, side, handle) {
    const shot = findShot(ctx, eventId, ctx.time());
    if (!shot || !shot.editable || !shot.record || !vector(handle, 2)) return false;
    const record = clone(shot.record);
    const index = record.keys.findIndex((key) => key.frame === frame);
    if (index < 0) return false;
    const key = record.keys[index];
    const handles = {};
    for (const name of CHANNELS) handles[name] = M.handles(record.keys, index, name);
    handles[channel][side] = side === "in" ? [Math.min(0, handle[0]), handle[1]] : [Math.max(0, handle[0]), handle[1]];
    key.handle = "free";
    key.handles = handles;
    if (key.interp !== "bezier" && side === "out") key.interp = "bezier";
    return commit(ctx, shot, record, "Edit camera handle", channel);
  }

  function setKeyProperty(ctx, property, value) {
    const found = targetKey(ctx);
    if (!found || !found.shot.editable) return false;
    const record = clone(found.shot.record);
    const index = record.keys.findIndex((key) => key.frame === found.key.frame);
    const key = record.keys[index];
    if (property === "interp" && M.INTERPOLATIONS.includes(value)) key.interp = value;
    else if (property === "handle" && M.HANDLES.includes(value)) {
      if (value === "free" && key.handle !== "free") {
        key.handles = Object.fromEntries(CHANNELS.map((channel) => [channel, M.handles(record.keys, index, channel)]));
      }
      key.handle = value;
      if (value !== "free") delete key.handles;
    } else if (property === "frame") {
      return moveKey(ctx, found.shot.event.id, key.frame, value);
    } else return false;
    const changed = commit(ctx, found.shot, record, property === "interp" ? "Change interpolation" : "Change handle type");
    renderPanel(ctx);
    return changed;
  }

  // Ease presets on the selected key's outgoing segment.
  function ease(ctx, preset) {
    const found = targetKey(ctx);
    if (!found || !found.shot.editable) return false;
    const record = clone(found.shot.record);
    const index = record.keys.findIndex((key) => key.frame === found.key.frame);
    const key = record.keys[index], next = record.keys[index + 1];
    const handle = (item, type) => { if (item) { item.handle = type; delete item.handles; } };
    if (preset === "linear") key.interp = "linear";
    else {
      key.interp = "bezier";
      if (preset === "ease-in-out") { handle(key, "flat"); handle(next, "flat"); }
      else if (preset === "ease-in") { handle(key, "flat"); handle(next, "auto-clamped"); }
      else if (preset === "ease-out") { handle(key, "auto-clamped"); handle(next, "flat"); }
      else return false;
    }
    const changed = commit(ctx, found.shot, record, "Apply ease preset", preset);
    renderPanel(ctx);
    return changed;
  }

  // Keys (absolute) at the given frames of the current base pose, Euler unwrapped key to key.
  function absoluteKeys(shot, record, frames, interp = "bezier") {
    const keys = [];
    let near = null;
    for (const frame of [...new Set(frames)].sort((a, b) => a - b)) {
      const pose = basePose(shot, record, frame);
      const value = absoluteOf(pose, near);
      near = { pan: value.pan, tilt: value.tilt, roll: value.roll };
      if (!finite(value.fov)) value.fov = shot.fallbackFov;
      keys.push({ frame, values: value, interp, handle: "auto-clamped" });
    }
    return keys;
  }

  function convertRecord(shot, record, mode, space) {
    if (mode === "original") return null;
    const frames = [0, shot.count - 1, ...(record ? record.keys.map((key) => key.frame) : [])];
    if (mode === "keys") {
      if (record && record.mode === "keys") return record;
      return { mode: "keys", space: record ? record.space : space, keys: absoluteKeys(shot, record, frames) };
    }
    // offset
    if (!record) return { mode: "offset", space, keys: [] };
    if (record.mode === "offset") {
      if (record.space === space) return record;
      // Same deltas in the other space, at each key.
      const keys = record.keys.map((key) => {
        const q = M.normalize(shot.source[key.frame].rotation), v = key.values;
        const moved = space === "world" ? M.rotateVector(q, [-v.x, v.y, -v.z]) : M.rotateVector(M.conjugate(q), [v.x, v.y, v.z]);
        const position = space === "world" ? { x: moved[0], y: moved[1], z: moved[2] } : { x: -moved[0], y: moved[1], z: -moved[2] };
        return { ...clone(key), values: { ...v, ...position } };
      });
      return { mode: "offset", space, keys };
    }
    // keys -> offset: deltas at the key frames.
    const target = { mode: "offset", space, keys: [] };
    let near = zeros();
    for (const key of record.keys) {
      const pose = basePose(shot, record, key.frame);
      const values = deltasFor(shot, target, key.frame, { x: pose.position[0], y: pose.position[1], z: pose.position[2], rotation: pose.rotation, fov: pose.fov },
        new Set(["position", "rotation", "fov"]), near);
      near = values;
      target.keys.push({ frame: key.frame, values, interp: key.interp, handle: key.handle === "free" ? "auto-clamped" : key.handle });
    }
    return target;
  }

  const CONFIRM = {
    original: "Remove the camera keys of this shot and play its original motion?",
    keys: "Replace this shot's motion with keys at its first and last frame and at every key?",
    offset: "Turn the keys into offsets over the original motion at the same frames?",
  };

  function setMode(ctx, mode, { confirm = true } = {}) {
    const shot = requireShot(ctx, playheadShot(ctx));
    if (!shot || !["original", "offset", "keys"].includes(mode)) return false;
    const current = shot.record ? shot.record.mode : "original";
    if (current === mode) return false;
    if (shot.user && mode !== "keys") return false;
    const lossy = (current === "offset" && shot.record.keys.length) || current === "keys" || (mode === "keys");
    if (confirm && lossy && typeof global.confirm === "function" && !global.confirm(t(ctx, CONFIRM[mode]))) { renderPanel(ctx, true); return false; }
    const record = convertRecord(shot, shot.record, mode, stateOf(ctx).space);
    const changed = commit(ctx, shot, record, "Change camera mode", mode);
    renderPanel(ctx, true);
    return changed;
  }

  function setSpace(ctx, space) {
    if (!["view", "world"].includes(space)) return false;
    stateOf(ctx).space = space;
    const shot = requireShot(ctx, playheadShot(ctx));
    if (!shot || !shot.record || shot.record.mode !== "offset" || shot.record.space === space) { renderPanel(ctx, true); return false; }
    const changed = commit(ctx, shot, convertRecord(shot, shot.record, "offset", space), "Change offset space", space);
    renderPanel(ctx, true);
    return changed;
  }

  // "Convert to keyframes": the current motion as linear keys within 2 mm / 0.05° / 0.01°.
  function convertToKeys(ctx) {
    const shot = requireShot(ctx, playheadShot(ctx));
    if (!shot) return false;
    const samples = [];
    let near = null;
    for (let frame = 0; frame < shot.count; frame++) {
      const value = absoluteOf(basePose(shot, shot.record, frame), near);
      near = value;
      if (!finite(value.fov)) value.fov = shot.fallbackFov;
      samples.push(value);
    }
    const kept = M.simplify(samples);
    const record = { mode: "keys", space: shot.record ? shot.record.space : stateOf(ctx).space,
      keys: kept.map((frame) => ({ frame, values: { ...samples[frame] }, interp: "linear", handle: "auto-clamped" })) };
    const changed = commit(ctx, shot, record, "Convert to keyframes", String(kept.length));
    renderPanel(ctx, true);
    return changed;
  }

  // Revert shot: one command removing the record and restoring timing and other values; the
  // rebake that follows restores the original samples.
  function revertShot(ctx, track, event) {
    const shot = shotInfo(ctx, track, event);
    if (!shot || shot.user || ctx.locked()) return false;
    const original = ctx.history.originals.get(event.id);
    const changes = [];
    if (recordOf(ctx, event.id) !== undefined) changes.push({ target: { kind: "editor" }, path: ["camera", "shots", event.id], after: undefined });
    if (original) {
      const target = { kind: "event", track: track.id, event: event.id };
      for (const key of ["start", "duration", "label"]) {
        if (JSON.stringify(event[key]) !== JSON.stringify(original[key])) changes.push({ target, path: [key], after: clone(original[key]) });
      }
      const before = original.values || {}, values = event.values || {};
      for (const key of new Set([...Object.keys(before), ...Object.keys(values)])) {
        if (key === "keyframes") continue;
        if (JSON.stringify(values[key]) !== JSON.stringify(before[key])) changes.push({ target, path: ["values", key], after: clone(before[key]) });
      }
      const Interact = global.MVStudioTimelineInteract;
      if (Interact && ctx.extrapolationAuto(track)) {
        const reverted = { ...event, start: original.start, duration: original.duration, values: { ...values, ...clone(before), keyframes: undefined } };
        const virtual = { ...track, events: track.events.map((item) => item === event ? reverted : item) };
        for (const write of Interact.extrapolationChanges(virtual, new Map())) {
          changes.push({ target: { kind: "event", track: track.id, event: write.event.id }, path: ["values", write.key], after: write.value });
        }
      }
    }
    if (!changes.length) return false;
    const changed = ctx.history.apply({ label: "Revert shot", detail: event.label || "", changes });
    if (stateOf(ctx).selected && stateOf(ctx).selected.event === event.id) stateOf(ctx).selected = null;
    renderPanel(ctx, true);
    return changed;
  }

  // A binding-less camera track (created once, outside history: tracks have no history
  // target) and a new shot on it, as one history command (non-native projects only).
  function ensureUserShot(ctx, start, end, pose) {
    const project = ctx.project();
    if (!project || project.nativeTimeline === true || ctx.locked()) return null;
    const duration = Math.max(0, project.duration);
    const from = clamp(Math.round(start * FRAME_RATE) / FRAME_RATE, 0, Math.max(0, duration - 2 / FRAME_RATE));
    const frames = Math.max(2, Math.round((clamp(end, from, duration) - from) * FRAME_RATE));
    const length = Math.min(frames / FRAME_RATE, duration - from);
    const count = Math.round(length * FRAME_RATE) + 1;
    let track = project.tracks.find((item) => item.id === USER_TRACK);
    if (!track) {
      track = { id: USER_TRACK, kind: "camera", label: t(ctx, "Camera (editor)"), events: [] };
      project.tracks.push(track);
    }
    const ids = new Set(project.tracks.flatMap((item) => item.events.map((event) => event.id)));
    let number = 1;
    while (ids.has(`${track.id}:u${number}`)) number++;
    const id = `${track.id}:u${number}`;
    const rig = pose || viewPose(ctx) || { position: [0, 1.4, 6], rotation: [0, 0, 0, 1], fov: 30 };
    const keyframes = Array.from({ length: count }, (_, index) => ({ time: index / FRAME_RATE, position: rig.position.slice(0, 3),
      rotation: M.normalize(rig.rotation), fov: clampFov(finite(rig.fov) ? rig.fov : 30) }));
    const event = { id, label: t(ctx, "Camera shot"), start: from, duration: (count - 1) / FRAME_RATE, values: { keyframes }, editableValues: ["keyframes"] };
    const euler = M.quaternionToEulerZXY(rig.rotation);
    const record = { mode: "keys", space: "view", keys: [{ frame: 0, values: { x: rig.position[0], y: rig.position[1], z: rig.position[2], ...euler,
      fov: keyframes[0].fov }, interp: "bezier", handle: "auto-clamped" }] };
    const editor = ctx.editor(false);
    const changes = [{ target: { kind: "track", track: track.id }, path: ["events"], op: "insert", index: track.events.length, value: event }];
    if (!editor || !editor.camera || editor.camera.version !== 1) changes.push({ target: { kind: "editor" }, path: ["camera", "version"], after: 1 });
    changes.push({ target: { kind: "editor" }, path: ["camera", "shots", id], after: record });
    if (!ctx.history.apply({ label: "New camera shot", changes })) return null;
    ctx.renderTimeline();
    const added = track.events.find((item) => item.id === id);
    return added ? { track, event: added } : null;
  }

  // The free view as an authored rig pose (binding-less shots have no lens correction).
  function viewPose(ctx) {
    const scene = ctx.scene();
    const view = scene && typeof scene.getViewPose === "function" ? scene.getViewPose() : null;
    return view ? { position: M.threeToUnityPosition(view.position), rotation: M.threeToUnityQuaternion(view.quaternion), fov: view.fov } : null;
  }

  function newShotAtPlayhead(ctx) {
    const created = ensureUserShot(ctx, ctx.time(), ctx.time() + 4);
    if (created) ctx.select(created.track.id, created.event.id);
    return created;
  }

  // ---- inspector: the dense samples become a summary ----------------------------------------
  function openPanel(ctx) {
    const panel = global.document && document.getElementById("mv-panel-camera");
    if (!panel || panel.hidden) return false;
    panel.open = true;
    renderPanel(ctx, true);
    panel.scrollIntoView?.({ block: "nearest" });
    panel.querySelector("button, select, input")?.focus({ preventScroll: true });
    return true;
  }

  function keyframeSummary(ctx, track, frames) {
    const box = ctx.make("div", null, { class: "mv-field mv-cam-summary" });
    const last = frames[frames.length - 1];
    const rate = frames.length > 1 && last && last.time > 0 ? Math.round((frames.length - 1) / last.time) : FRAME_RATE;
    box.append(ctx.make("span", t(ctx, "Keyframes")), ctx.make("output", format(ctx, "{count} samples · {rate} Hz", { count: frames.length, rate })));
    if (mainTrack(track)) box.append(ctx.button(t(ctx, "Open camera editor"), () => openPanel(ctx), { class: "mv-cam-open" }));
    return box;
  }

  // ---- timeline: key diamonds on the MainCamera lane ------------------------------------------
  function decorate(ctx, track, lane, layout) {
    if (!mainTrack(track) || !global.document) return;
    const state = stateOf(ctx);
    for (const event of track.events) {
      const shot = shotInfo(ctx, track, event);
      if (!shot || !shot.record || !shot.record.keys.length) continue;
      for (const key of shot.record.keys) {
        const time = frameTime(shot, key.frame);
        const selected = !!state.selected && state.selected.event === event.id && state.selected.frame === key.frame;
        const diamond = ctx.make("button", null, { type: "button", class: "mv-key mv-cam-key", "data-event": event.id, "data-frame": String(key.frame),
          "aria-label": format(ctx, "Key {time}", { time: formatTime(time) }), title: format(ctx, "Key {time}", { time: formatTime(time) }),
          "aria-pressed": String(selected) });
        diamond.style.left = `${time * layout.pixelsPerSecond}px`;
        diamond.style.setProperty("--mv-clip-row", layout.rowOf.get(event.id) || 0);
        if (selected) diamond.classList.add("mv-selected");
        attachDiamond(ctx, diamond, shot.event.id, key.frame, layout);
        lane.append(diamond);
      }
    }
  }

  function attachDiamond(ctx, diamond, eventId, frame, layout) {
    let drag = null;
    const locate = (event) => {
      const shot = findShot(ctx, eventId);
      if (!shot) return null;
      const pps = layout.pixelsPerSecond;
      let time = frameTime(shot, frame) + (event.clientX - drag.x) / pps;
      // Playhead snap within 6 px (Alt: frames only).
      if (!event.altKey && Math.abs(ctx.time() - time) * pps <= 6) time = ctx.time();
      return { shot, frame: clamp(Math.round((time - shot.event.start) * FRAME_RATE), 0, shot.count - 1) };
    };
    diamond.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || ctx.locked()) return;
      event.stopPropagation();
      drag = { x: event.clientX, id: event.pointerId, moved: false, frame };
      diamond.setPointerCapture?.(event.pointerId);
    });
    diamond.addEventListener("pointermove", (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      if (!drag.moved && Math.abs(event.clientX - drag.x) < 3) return;
      drag.moved = true;
      const found = locate(event);
      if (!found) return;
      drag.frame = found.frame;
      diamond.style.left = `${frameTime(found.shot, found.frame) * layout.pixelsPerSecond}px`;
      diamond.classList.add("mv-dragging");
    });
    const finish = (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      const ended = drag;
      drag = null;
      diamond.classList.remove("mv-dragging");
      if (event.type === "pointercancel") { ctx.refreshLane(diamond.closest?.(".mv-lane")?.dataset.track); return; }
      const shot = findShot(ctx, eventId);
      if (!shot) return;
      if (ended.moved && ended.frame !== frame) {
        moveKey(ctx, eventId, frame, ended.frame);
        const moved = selectedFrame(ctx, eventId);
        ctx.seek(frameTime(shot, moved === null ? frame : moved), { audio: false });
      } else {
        select(ctx, shot, frame);
        ctx.seek(frameTime(shot, frame), { audio: false });
      }
      ctx.refreshLane(shot.track.id);
      renderPanel(ctx);
    };
    diamond.addEventListener("pointerup", finish);
    diamond.addEventListener("pointercancel", finish);
    diamond.addEventListener("click", (event) => {
      event.stopPropagation();
      // Keyboard activation (pointer clicks were handled on release).
      if (event.detail === 0) {
        const shot = findShot(ctx, eventId);
        if (!shot) return;
        select(ctx, shot, frame);
        ctx.seek(frameTime(shot, frame), { audio: false });
        ctx.refreshLane(shot.track.id);
        renderPanel(ctx);
      }
    });
    diamond.addEventListener("keydown", (event) => {
      if (!event.altKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight") || ctx.locked()) return;
      event.preventDefault();
      event.stopPropagation();
      const step = (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 10 : 1);
      if (moveKey(ctx, eventId, frame, frame + step)) {
        const shot = findShot(ctx, eventId), moved = selectedFrame(ctx, eventId);
        if (shot && moved !== null) ctx.seek(frameTime(shot, moved), { audio: false });
        const lane = shot && document.querySelector(`.mv-lane[data-track="${CSS.escape(shot.track.id)}"]`);
        lane?.querySelector(`.mv-cam-key[data-event="${CSS.escape(eventId)}"][data-frame="${moved}"]`)?.focus({ preventScroll: true });
      }
    });
  }

  function selectedFrame(ctx, eventId) {
    const selected = stateOf(ctx).selected;
    return selected && selected.event === eventId ? selected.frame : null;
  }

  // ---- the Camera editor panel ------------------------------------------------------------------
  const MODES = [["original", "Original motion"], ["offset", "Offset keys"], ["keys", "Keyframes (replace)"]];
  const LABELS = { x: "X", y: "Y", z: "Z", pan: "Pan", tilt: "Tilt", roll: "Roll", fov: "FOV" };
  const VIEW_LABELS = { x: "Truck", y: "Pedestal", z: "Dolly" };
  const INTERP_LABELS = { constant: "Constant", linear: "Linear", bezier: "Bezier" };
  const HANDLE_LABELS = { "auto-clamped": "Auto clamped", auto: "Automatic", flat: "Flat", free: "Free" };
  const EASES = [["linear", "Linear"], ["ease-in-out", "Ease in-out"], ["ease-in", "Ease in"], ["ease-out", "Ease out"]];
  const STEP = { x: .01, y: .01, z: .01, pan: .1, tilt: .1, roll: .1, fov: .1 };
  const round = (value, digits) => finite(value) ? Number(value.toFixed(digits)) : "";

  function panelAvailable(ctx) {
    const project = ctx.project();
    if (!project) return false;
    if (project.nativeTimeline !== true) return true;
    return mainCameraShots(ctx).some(({ track, event }) => shotInfo(ctx, track, event)?.editable);
  }

  function panelOpen() {
    const panel = global.document && document.getElementById("mv-panel-camera");
    return !!panel && panel.open && !panel.hidden;
  }

  function renderPanel(ctx, force = false) {
    if (!global.document) return;
    const state = stateOf(ctx);
    if (force) state.panel = null;
    if (typeof ctx.renderPanel === "function") ctx.renderPanel("camera");
  }

  function numberField(ctx, name, label, onChange) {
    const input = ctx.make("input", null, { type: "number", step: "any", "data-mv-cam": name, "aria-label": label, title: label });
    input.addEventListener("change", () => {
      if (input.value === "" || !finite(input.valueAsNumber)) return;
      onChange(input.valueAsNumber);
    });
    const wrap = ctx.make("label", null, { class: "mv-cam-number" });
    wrap.append(ctx.make("span", label), input);
    return { wrap, input };
  }

  function choice(ctx, attrs, options, onChange) {
    const control = ctx.make("select", null, attrs);
    for (const [value, label] of options) control.append(new Option(t(ctx, label), value));
    control.addEventListener("change", () => onChange(control.value));
    return control;
  }

  function signature(ctx, shot) {
    if (!shot) return "none|" + (ctx.project() ? ctx.project().nativeTimeline === true : "");
    return [shot.event.id, shot.editable, shot.record ? shot.record.mode : "original", shot.record ? shot.record.space : "", shot.user,
      ctx.locked()].join("|");
  }

  function build(ctx, box, shot) {
    const state = stateOf(ctx);
    const refs = { inputs: {}, rows: {} };
    const root = ctx.make("div", null, { class: "mv-cam-editor" });
    refs.root = root;
    box.replaceChildren(root);
    if (!shot) {
      root.append(ctx.make("p", t(ctx, "No camera shot at the playhead."), { class: "mv-field-note", id: "mv-cam-empty" }));
      if (ctx.project() && ctx.project().nativeTimeline !== true) {
        const add = ctx.button(t(ctx, "New camera shot at playhead"), () => newShotAtPlayhead(ctx), { id: "mv-cam-new-shot" });
        add.disabled = ctx.locked();
        root.append(add);
      }
      return refs;
    }
    refs.header = ctx.make("p", null, { class: "mv-cam-shot", id: "mv-cam-shot" });
    root.append(refs.header);
    if (!shot.editable) {
      root.append(ctx.make("p", t(ctx, shot.reason || "This camera shot cannot be edited."), { class: "mv-field-note", id: "mv-cam-locked" }));
      if (shot.lengthChanged) root.append(ctx.button(t(ctx, "Revert shot"), () => revertShot(ctx, shot.track, shot.event), { id: "mv-cam-revert" }));
      return refs;
    }
    const locked = ctx.locked();
    const mode = shot.record ? shot.record.mode : "original";
    const modes = shot.user ? MODES.filter(([id]) => id === "keys") : MODES;
    const modeSelect = choice(ctx, { id: "mv-cam-shot-mode" }, modes, (value) => setMode(ctx, value));
    modeSelect.value = mode;
    const settings = ctx.make("div", null, { class: "mv-form-grid mv-cam-settings" });
    const modeLabel = ctx.make("label");
    modeLabel.append(ctx.make("span", t(ctx, "Camera mode")), modeSelect);
    settings.append(modeLabel);
    if (mode !== "keys") {
      const space = choice(ctx, { id: "mv-cam-space" }, [["view", "View-relative"], ["world", "World"]], (value) => setSpace(ctx, value));
      space.value = shot.record ? shot.record.space : state.space;
      const spaceLabel = ctx.make("label");
      spaceLabel.append(ctx.make("span", t(ctx, "Offset space")), space);
      settings.append(spaceLabel);
    }
    root.append(settings);

    // Toolbar.
    const bar = ctx.make("div", null, { class: "mv-cam-toolbar", role: "toolbar", "aria-label": t(ctx, "Camera keys") });
    const tool = (id, label, shortcut, action) => {
      const control = ctx.button(t(ctx, label), action, { id, class: "mv-cam-tool", title: shortcut ? `${t(ctx, label)} (${shortcut})` : t(ctx, label) });
      if (shortcut) control.setAttribute("aria-keyshortcuts", shortcut.replace("Ctrl/Cmd", "Control"));
      bar.append(control);
      return control;
    };
    refs.keyView = tool("mv-cam-key-view", "Key current view", "K", () => keyView(ctx));
    refs.keyView.classList.add("mv-cam-primary");
    refs.addKey = tool("mv-cam-add-key", "Add key", "I", () => addKey(ctx));
    refs.duplicate = tool("mv-cam-duplicate-key", "Duplicate key", "Ctrl/Cmd+D", () => duplicateKey(ctx));
    refs.remove = tool("mv-cam-delete-key", "Delete key", "Delete", () => deleteKey(ctx));
    refs.previous = tool("mv-cam-prev-key", "Previous key", "[", () => stepKey(ctx, -1));
    refs.next = tool("mv-cam-next-key", "Next key", "]", () => stepKey(ctx, 1));
    tool("mv-cam-align", "Align view to game camera", "", () => alignView(ctx));
    if (!shot.user) refs.revert = tool("mv-cam-revert", "Revert shot", "", () => revertShot(ctx, shot.track, shot.event));
    refs.simplify = tool("mv-cam-simplify", "Convert to keyframes", "", () => convertToKeys(ctx));
    const auto = ctx.make("label", null, { class: "mv-cam-autokey" });
    refs.autoKey = ctx.make("input", null, { type: "checkbox", id: "mv-cam-autokey" });
    refs.autoKey.checked = state.autoKey;
    refs.autoKey.addEventListener("change", () => { state.autoKey = refs.autoKey.checked; });
    auto.append(refs.autoKey, ctx.make("span", t(ctx, "Auto key")));
    auto.title = t(ctx, "Keys the free camera view every time you finish moving it.");
    bar.append(auto);
    root.append(bar);

    // At-playhead fields.
    const values = ctx.make("fieldset", null, { class: "mv-cam-values" });
    values.append(ctx.make("legend", t(ctx, "At the playhead")));
    const rows = mode === "keys" ? [["absolute", "Value"]] : [["offset", "Offset"], ["absolute", "Result"]];
    for (const [row, title] of rows) {
      const group = ctx.make("div", null, { class: "mv-cam-row", "data-mv-cam-row": row });
      group.append(ctx.make("p", t(ctx, title), { class: "mv-cam-row-title" }));
      for (const set of [M.POSITION, M.ROTATION, ["fov"]]) {
        const line = ctx.make("div", null, { class: "mv-cam-vector" });
        for (const channel of set) {
          const space = shot.record ? shot.record.space : state.space;
          const label = row === "offset" && M.POSITION.includes(channel) && space === "view" ? VIEW_LABELS[channel] : LABELS[channel];
          const field = numberField(ctx, `${row}.${channel}`, t(ctx, label), (value) => setChannels(ctx, row, { [channel]: value }));
          field.input.step = String(STEP[channel]);
          field.input.disabled = locked;
          refs.inputs[`${row}.${channel}`] = field.input;
          line.append(field.wrap);
        }
        group.append(line);
      }
      values.append(group);
    }
    root.append(values);

    // Selected key (hidden while no key is selected).
    {
      const box = ctx.make("fieldset", null, { class: "mv-cam-key-fields", id: "mv-cam-key" });
      refs.keyBox = box;
      box.append(ctx.make("legend", t(ctx, "Selected key")));
      const grid = ctx.make("div", null, { class: "mv-form-grid" });
      const frame = numberField(ctx, "key.frame", t(ctx, "Frame"), (value) => setKeyProperty(ctx, "frame", Math.round(value)));
      frame.input.step = "1"; frame.input.min = "0"; frame.input.max = String(shot.count - 1);
      refs.inputs["key.frame"] = frame.input;
      refs.keyTime = ctx.make("output", null, { class: "mv-cam-key-time" });
      const frameRow = ctx.make("label");
      frameRow.append(ctx.make("span", t(ctx, "Frame")), (() => { const line = ctx.make("span", null, { class: "mv-inline-fields" }); line.append(frame.input, refs.keyTime); return line; })());
      const interp = choice(ctx, { id: "mv-cam-interp" }, M.INTERPOLATIONS.map((id) => [id, INTERP_LABELS[id]]), (value) => setKeyProperty(ctx, "interp", value));
      const handle = choice(ctx, { id: "mv-cam-handle" }, M.HANDLES.map((id) => [id, HANDLE_LABELS[id]]), (value) => setKeyProperty(ctx, "handle", value));
      refs.interp = interp; refs.handle = handle;
      const interpRow = ctx.make("label"), handleRow = ctx.make("label");
      interpRow.append(ctx.make("span", t(ctx, "Interpolation")), interp);
      handleRow.append(ctx.make("span", t(ctx, "Handles")), handle);
      grid.append(frameRow, interpRow, handleRow);
      const eases = ctx.make("div", null, { class: "mv-cam-eases", role: "group", "aria-label": t(ctx, "Ease presets") });
      for (const [id, label] of EASES) eases.append(ctx.button(t(ctx, label), () => ease(ctx, id), { "data-mv-cam-ease": id }));
      box.append(grid, eases);
      for (const control of box.querySelectorAll("input, select, button")) control.disabled = locked;
      root.append(box);
    }

    // Curve view.
    if (global.MVStudioCameraCurves) {
      const chips = ctx.make("div", null, { class: "mv-cam-chips", role: "group", "aria-label": t(ctx, "Curve channels") });
      for (const channel of CHANNELS) {
        const chip = ctx.button(t(ctx, LABELS[channel]), () => {
          const list = new Set(state.channels);
          if (list.has(channel) && list.size > 1) list.delete(channel); else list.add(channel);
          state.channels = CHANNELS.filter((item) => list.has(item));
          syncPanel(ctx);
        }, { class: "mv-cam-chip", "data-mv-cam-channel": channel, "aria-pressed": "false" });
        chip.style.setProperty("--mv-cam-color", global.MVStudioCameraCurves.COLORS[channel]);
        chips.append(chip);
      }
      refs.chips = chips;
      const view = ctx.make("div", null, { class: "mv-cam-curves", id: "mv-cam-curves" });
      root.append(chips, view);
      refs.curves = global.MVStudioCameraCurves.create(view, curveHandlers(ctx));
    }
    refs.note = ctx.make("p", null, { class: "mv-field-note mv-cam-note", "aria-live": "polite" });
    root.append(refs.note);
    return refs;
  }

  function curveHandlers(ctx) {
    let token = null, dragging = null;
    const owner = () => document.getElementById("mv-cam-curves");
    const begin = (label) => { token = ctx.history.begin(label, { owner: owner() }); };
    const end = () => { if (token) ctx.history.end(token); token = null; };
    return {
      t: (label) => t(ctx, label),
      onSelectKey(frame) {
        const shot = playheadShot(ctx);
        if (!shot) return;
        select(ctx, shot, frame);
        ctx.seek(frameTime(shot, frame), { audio: false });
        ctx.refreshLane(shot.track.id);
        renderPanel(ctx);
      },
      onSeek(frame) {
        const shot = playheadShot(ctx);
        if (shot) ctx.seek(frameTime(shot, frame), { audio: false });
      },
      onDragKey(phase, { from, frame, channel, value }) {
        const shot = dragging ? findShot(ctx, dragging.event) : playheadShot(ctx);
        if (!shot) return null;
        if (phase === "begin") { dragging = { event: shot.event.id, frame: from }; begin("Move camera key"); return from; }
        if (phase === "end") { end(); const done = dragging; dragging = null; if (done) ctx.refreshLane(shot.track.id); return null; }
        const next = setKeyValue(ctx, shot.event.id, dragging.frame, { frame, channel, value });
        if (next !== null) dragging.frame = next;
        return dragging.frame;
      },
      onDragHandle(phase, { frame, channel, side, handle }) {
        if (phase === "begin") { begin("Edit camera handle"); return; }
        if (phase === "end") { end(); return; }
        const shot = playheadShot(ctx);
        if (shot) setHandle(ctx, shot.event.id, frame, channel, side, handle);
      },
    };
  }

  function alignView(ctx) {
    const scene = ctx.scene();
    if (!scene || typeof scene.alignViewToGame !== "function") return false;
    const mode = global.document && document.getElementById("mv-camera-mode");
    if (mode && mode.value !== "orbit") {
      mode.value = "orbit";
      mode.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return scene.alignViewToGame() !== false;
  }

  // Dense curve of each channel in the record's space (deltas for offset, absolute otherwise).
  function denseCurves(ctx, shot, channels) {
    const frames = shot.event.values && Array.isArray(shot.event.values.keyframes) && shot.event.values.keyframes.length === shot.count
      ? shot.event.values.keyframes : shot.source;
    const record = shot.record, offset = record && record.mode === "offset";
    const dense = Object.fromEntries(channels.map((channel) => [channel, new Float64Array(shot.count)]));
    let near = null;
    for (let index = 0; index < shot.count; index++) {
      const frame = frames[index], sample = shot.source[index];
      let value;
      if (offset) {
        value = deltasFor(shot, record, index, { x: frame.position[0], y: frame.position[1], z: frame.position[2], rotation: frame.rotation, fov: frame.fov },
          new Set(["position", "rotation", "fov"]), near || zeros());
        if (!finite(frame.fov) || !finite(sample.fov)) value.fov = 0;
      } else value = absoluteOf(frame, near);
      near = value;
      for (const channel of channels) dense[channel][index] = finite(value[channel]) ? value[channel] : NaN;
    }
    return dense;
  }

  function syncPanel(ctx) {
    const state = stateOf(ctx), refs = state.panel && state.panel.refs;
    if (!refs) return;
    const shot = playheadShot(ctx);
    if (!shot || !shot.source) return;
    const frame = shot.frame;
    if (refs.header) {
      refs.header.textContent = [format(ctx, "Shot {index} / {count}", { index: shot.index + 1, count: shot.total }), shot.event.label || "",
        format(ctx, "Frame {frame} / {last}", { frame, last: shot.count - 1 }) + ` (${formatTime(frameTime(shot, frame) - shot.event.start)})`]
        .filter(Boolean).join(" · ");
    }
    if (!shot.editable) return;
    const record = shot.record;
    const focused = global.document && document.activeElement;
    const put = (name, value, digits) => {
      const input = refs.inputs[name];
      if (input && input !== focused) input.value = round(value, digits);
    };
    const current = channelValues(shot, record, frame);
    const absolute = absoluteOf(basePose(shot, record, frame), record && record.mode === "keys" ? current : M.quaternionToEulerZXY(shot.source[frame].rotation));
    for (const channel of CHANNELS) {
      const digits = M.POSITION.includes(channel) ? 4 : 3;
      if (!record || record.mode === "offset") put(`offset.${channel}`, current[channel], digits);
      put(`absolute.${channel}`, record && record.mode === "keys" ? current[channel] : absolute[channel], digits);
    }
    const key = selectedKey(ctx, shot);
    const atKey = !!(record && record.keys.some((item) => item.frame === frame));
    for (const input of Object.values(refs.inputs)) input.classList.toggle("mv-cam-keyed", atKey && !input.dataset.mvCam.startsWith("key."));
    if (refs.keyBox) refs.keyBox.hidden = !key;
    if (key) {
      put("key.frame", key.frame, 0);
      if (refs.keyTime) refs.keyTime.textContent = formatTime(frameTime(shot, key.frame));
      if (refs.interp && refs.interp !== focused) refs.interp.value = key.interp;
      if (refs.handle && refs.handle !== focused) refs.handle.value = key.handle;
    }
    const keys = record ? record.keys : [];
    if (refs.remove) refs.remove.disabled = ctx.locked() || !(key || atKey);
    if (refs.duplicate) refs.duplicate.disabled = ctx.locked() || !key || key.frame === frame;
    if (refs.previous) refs.previous.disabled = !keys.some((item) => item.frame < frame);
    if (refs.next) refs.next.disabled = !keys.some((item) => item.frame > frame);
    if (refs.revert) refs.revert.disabled = ctx.locked() || !(record || ctx.edited(shot.event.id));
    if (refs.chips) for (const chip of refs.chips.children) chip.setAttribute("aria-pressed", String(state.channels.includes(chip.dataset.mvCamChannel)));
    if (refs.curves) {
      refs.curves.update({ count: shot.count, keys, mode: record ? record.mode : "original", channels: state.channels,
        dense: denseCurves(ctx, shot, state.channels), playhead: (ctx.time() - shot.event.start) * FRAME_RATE,
        selected: key ? key.frame : null, labels: Object.fromEntries(CHANNELS.map((channel) => [channel, t(ctx, LABELS[channel])])) });
    }
    if (refs.note) {
      const notes = [];
      if (layers.length && affecting(ctx, shot).length) notes.push(t(ctx, "A camera rig also moves this shot."));
      if (differs(ctx, shot.event)) notes.push(t(ctx, "Duration is locked while this shot has camera edits."));
      refs.note.textContent = notes.join(" ");
    }
  }

  function renderInto(box, ctx) {
    const state = stateOf(ctx);
    const shot = ctx.project() ? playheadShot(ctx) : null;
    const key = signature(ctx, shot);
    if (!state.panel || state.panel.box !== box || state.panel.key !== key || !box.contains(state.panel.refs.root)) {
      // A rebuild (a new mode or shot) keeps keyboard focus on the same control.
      const active = global.document && document.activeElement;
      const focused = active && box.contains(active) ? (active.dataset && active.dataset.mvCam ? `[data-mv-cam="${active.dataset.mvCam}"]` : active.id ? `#${active.id}` : null) : null;
      state.panel = { box, key, refs: build(ctx, box, shot) };
      if (focused) box.querySelector(focused)?.focus({ preventScroll: true });
    }
    syncPanel(ctx);
  }

  // ---- scene hooks: auto key and the frustum helper --------------------------------------------
  function hookScene(ctx) {
    const state = stateOf(ctx), scene = ctx.scene();
    if (!scene || state.scene === scene) return;
    if (state.unsubscribe) state.unsubscribe();
    state.scene = scene;
    state.unsubscribe = typeof scene.onViewChange === "function" ? scene.onViewChange(() => {
      if (state.autoKey && !ctx.playing() && !ctx.locked()) keyView(ctx, { auto: true });
    }) : null;
    if (typeof scene.setGameCameraHelper === "function") scene.setGameCameraHelper(true);
  }

  // History changes that need a rebake: camera records, rigs, or a main-camera shot's timing.
  function bakeScope(ctx, command) {
    let all = false;
    const ids = new Set();
    const main = new Set(mainTracks(ctx.project()).map((track) => track.id));
    for (const change of command && Array.isArray(command.changes) ? command.changes : []) {
      const target = change.target || {}, path = change.path || [];
      if (target.kind === "editor" && path[0] === "camera") {
        if (path[1] === "shots" && typeof path[2] === "string") ids.add(path[2]);
        else all = true;
      } else if (target.kind === "event" && main.has(target.track)) ids.add(target.event);
      else if (target.kind === "track" && main.has(target.track)) all = true;
    }
    if (all) return { events: undefined };
    return ids.size ? { events: [...ids] } : null;
  }

  const plugin = {
    id: "camera-keys",
    order: 8,
    attach(ctx) { stateOf(ctx); },
    panels: [{
      key: "camera", name: "Camera editor", open: false,
      available: (ctx) => panelAvailable(ctx),
      render: (box, ctx) => renderInto(box, ctx),
    }],
    projectChanged(ctx, info = {}) {
      const state = stateOf(ctx);
      hookScene(ctx);
      // A project as opened or saved already holds its bakes: nothing is rebaked on load.
      if (info.reason === "load") {
        state.selected = null;
        state.differs = new WeakMap();
        state.panel = null;
        renderPanel(ctx);
        return;
      }
      // An asset import (reload) or a costume re-import can change what layers bake (members,
      // outfits); keys alone rebake to the same samples. Unedited shots are not visited.
      if (info.reason === "reload" || info.reason === "reimport") { state.panel = null; requestBake(ctx, { reason: info.reason }); }
      else if (info.reason === "history") {
        const scope = bakeScope(ctx, info.command);
        if (scope) requestBake(ctx, { events: scope.events, reason: "history" });
        else renderPanel(ctx);
      } else renderPanel(ctx);
    },
    timeChanged(ctx) {
      hookScene(ctx);
      if (!panelOpen()) return;
      const state = stateOf(ctx), shot = playheadShot(ctx);
      const key = signature(ctx, shot);
      if (state.panel && state.panel.key === key) syncPanel(ctx);
      else renderPanel(ctx);
    },
    selectionChanged(ctx, selection) {
      if (!selection || !mainTrack(selection.track)) return;
      const panel = global.document && document.getElementById("mv-panel-camera");
      if (panel && !panel.hidden && !panel.open && shotInfo(ctx, selection.track, selection.event)?.editable) panel.open = true;
      renderPanel(ctx);
    },
    valueControl(ctx, info) {
      if (!info || !info.track || info.track.kind !== "camera") return undefined;
      if (info.key === "keyframes" && Array.isArray(info.value)) return keyframeSummary(ctx, info.track, info.value);
      if (RAW_FIELDS.includes(info.key)) return null;
      // A static (non-native) shot that the editor has baked: its keys own the pose.
      if (["position", "rotation", "fov"].includes(info.key) && mainTrack(info.track) && recordOf(ctx, info.event.id)) return null;
      return undefined;
    },
    laneDecorate(ctx, track, lane, layout) { decorate(ctx, track, lane, layout); },
    clipConstraints(ctx, track, event) {
      if (!mainTrack(track) || !differs(ctx, event)) return undefined;
      return { resize: false, reason: t(ctx, "Duration is locked while this shot has camera edits.") };
    },
    revertEvent(ctx, track, event) {
      if (!mainTrack(track)) return false;
      const shot = shotInfo(ctx, track, event);
      if (!shot || !shot.source || shot.user) return false;
      revertShot(ctx, track, event);
      return true;
    },
    keydown(ctx, event) {
      const tab = typeof ctx.activeTab === "function" ? ctx.activeTab() : "";
      if (!panelOpen() && tab !== "camera" && tab !== "edit") return false;
      const key = String(event.key || "");
      const command = event.ctrlKey || event.metaKey;
      if (command && !event.altKey && !event.shiftKey && key.toLowerCase() === "d") { duplicateKey(ctx); return true; }
      if (command || event.altKey) return false;
      switch (key.toLowerCase()) {
        case "k": keyView(ctx); return true;
        case "i": addKey(ctx); return true;
        case "delete": case "backspace": return deleteKey(ctx) || !!targetKey(ctx);
        case "[": stepKey(ctx, -1); return true;
        case "]": stepKey(ctx, 1); return true;
        default: return false;
      }
    },
    async beforeSave(ctx) { await (stateOf(ctx).pending || null); },
    async beforeExport(ctx) {
      await (stateOf(ctx).pending || null);
      for (const { event } of mainCameraShots(ctx)) {
        const original = ctx.history.originals.get(event.id);
        if (original && original.duration !== event.duration && differs(ctx, event)) {
          throw new Error("Restore the original length of camera shots with camera edits before exporting.");
        }
      }
    },
  };

  // Every UI string of this module (English sources of webtools/i18n.py).
  const STRINGS = Object.freeze([
    "Camera editor", "Keyframes", "{count} samples · {rate} Hz", "Open camera editor", "Key {time}",
    "Original motion", "Offset keys", "Keyframes (replace)", "Camera mode", "Offset space", "View-relative", "World",
    "Camera keys", "Key current view", "Add key", "Duplicate key", "Delete key", "Previous key", "Next key",
    "Align view to game camera", "Revert shot", "Convert to keyframes", "Auto key",
    "Keys the free camera view every time you finish moving it.", "At the playhead", "Value", "Offset", "Result",
    "X", "Y", "Z", "Pan", "Tilt", "Roll", "FOV", "Truck", "Pedestal", "Dolly",
    "Selected key", "Frame", "Interpolation", "Handles", "Constant", "Linear", "Bezier",
    "Auto clamped", "Automatic", "Flat", "Free", "Ease presets", "Ease in-out", "Ease in", "Ease out", "Curve channels",
    "Shot {index} / {count}", "Frame {frame} / {last}", "No camera shot at the playhead.", "New camera shot at playhead",
    "Camera shot", "Camera (editor)", "This camera shot cannot be edited.", "The camera samples of this shot cannot be exported.",
    "Restore this shot's original length to edit its camera.", "Switch the preview camera to Free camera to key the view.",
    "Duration is locked while this shot has camera edits.", "A camera rig also moves this shot.",
    "Restore the original length of camera shots with camera edits before exporting.", "The camera could not be baked.",
    "Edit camera key", "Move camera key", "Delete camera key", "Duplicate camera key", "Edit camera handle", "Change interpolation",
    "Change handle type", "Apply ease preset", "Change camera mode", "Change offset space", "New camera shot", "Add camera key",
    ...Object.values(CONFIRM),
  ]);

  (global.MVStudioPlugins ||= []).push(plugin);
  global.MVStudioCameraKeys = Object.freeze({
    plugin, STRINGS, USER_TRACK,
    // Lane D (follow camera) and other layers.
    registerLayer, unregisterLayer, requestBake, mainCameraShots, ensureUserShot,
    // Model, bake and commands (also used by the tests).
    shotInfo, findShot, playheadShot, normalizeRecord, basePose, bakeShot, differs, channelValues,
    setChannels, keyView, addKey, deleteKey, duplicateKey, stepKey, moveKey, setKeyValue, setHandle, setKeyProperty, ease,
    setMode, setSpace, convertToKeys, revertShot, newShotAtPlayhead, selectKey: (ctx, eventId, frame) => {
      const shot = findShot(ctx, eventId);
      if (shot) select(ctx, shot, frame);
    },
    selected: (ctx) => stateOf(ctx).selected && { ...stateOf(ctx).selected },
    pending: (ctx) => stateOf(ctx).pending || Promise.resolve(),
  });
})(typeof window !== "undefined" ? window : globalThis);
