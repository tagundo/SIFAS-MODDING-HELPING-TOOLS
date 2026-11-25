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
  // The native camera writer accepts positions within ±1e6 m (mv_studio_timeline._camera_vector).
  const POSITION_LIMIT = 1e6;
  const zeros = () => Object.fromEntries(CHANNELS.map((channel) => [channel, 0]));

  // ---- per-editor state (one ctx per MV Studio mount; tests make several) -----------------
  const states = new WeakMap();
  function stateOf(ctx) {
    let state = states.get(ctx);
    if (!state) {
      // selected: { event, frames (sorted), frame (the active key) } — see "key selection".
      state = { selected: null, channels: ["x"], autoKey: false, space: "view", pending: null, controller: null, events: undefined,
        scene: null, unsubscribe: null, panel: null, curves: null, differs: new WeakMap(), lastShot: null, helper: false,
        toggle: null, echo: null, refreshed: null, dense: null, clipboard: null, memory: new Map(), multi: false };
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

  // The 60 Hz grid of a clip, as the importer samples one: ceil(duration·60)+1 samples at
  // index/60, the last one at the clip's end.
  const gridCount = (duration) => Math.max(2, Math.ceil(Math.max(0, duration) * FRAME_RATE - 1e-6) + 1);
  const gridTime = (index, duration) => Math.min(index / FRAME_RATE, duration);

  // A static shot (position/rotation/fov values, non-native projects) on a 60 Hz grid.
  function staticGrid(values, duration) {
    return Array.from({ length: gridCount(duration) }, (_, index) => ({ time: gridTime(index, duration),
      position: values.position.slice(0, 3), rotation: values.rotation.slice(0, 4), fov: finite(values.fov) ? values.fov : null }));
  }

  // The samples of a shot whose keys own its pose, on the grid of the clip's current length:
  // kept as they are while they sit on it; otherwise sampled by time as the scene plays them
  // (the last pose held past the end), never by index.
  function userGrid(frames, duration) {
    const count = gridCount(duration);
    if (frames.length === count && frames.every((frame, index) => frame.time === gridTime(index, duration))) return frames;
    const ordered = frames.every((frame, index) => !index || frame.time >= frames[index - 1].time);
    return Array.from({ length: count }, (_, index) => {
      const time = gridTime(index, duration);
      // The two samples around `time` (a binary search on ordered samples), then the scene's interpolation.
      let around = frames;
      if (ordered) {
        const [lower, upper] = M.sampleIndex(frames, time);
        around = lower === upper ? [frames[lower]] : [frames[lower], frames[upper]];
      }
      const pose = M.sampleFrames(around, time);
      return { time, position: pose.position, rotation: pose.rotation, fov: finite(pose.fov) ? pose.fov : null };
    });
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
    let source = null, staticSource = false, regrid = false;
    if (validFrames(values.keyframes)) source = values.keyframes;
    else if (!user && vector(current.position, 3) && vector(current.rotation, 4) && project && project.nativeTimeline !== true) {
      source = staticGrid(current, event.duration);
      staticSource = true;
    }
    // A shot added on the timeline is never exported natively, so it can be resized. When its
    // keys own its pose (a keys record with keys, as a shot made in the editor starts), its 60 Hz
    // grid follows the clip's length. Otherwise its samples are its only motion (Duplicate clip
    // copies a clip's samples, not its keys) and stay exactly as they are: it has no source to
    // bake from, so a record that does not own the pose is ignored until an edit claims the
    // shot (editStart).
    const raw = recordOf(ctx, event.id);
    const keyed = user && source ? normalizeRecord(raw, source.length) : null;
    const owned = !!keyed && keyed.mode === "keys" && keyed.keys.length > 0;
    if (owned) {
      const grid = userGrid(source, event.duration);
      regrid = grid !== source;
      source = grid;
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
    const info = { track, event, source, count, user, owned, native, staticSource, regrid, editable, reason, lengthChanged,
      record: source && (!user || owned) ? normalizeRecord(raw, count) : null,
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

  // endedCameraEvent of the scene: the clip that ends last on the track, once `time` is past
  // its end (an original MV holds its final pose). A gap between two shots is no shot.
  function endedCameraEvent(track, time) {
    let last = null;
    for (const event of track.events) if (event && (!last || event.start + event.duration > last.start + last.duration)) last = event;
    return last && time > last.start + last.duration ? last : null;
  }

  // The shot the game camera shows at `time`, as the scene's mainCameraAt picks it: the last
  // main-camera track with an active shot wins; otherwise, for game sources, the shot that
  // ends last among the tracks the playhead has run past.
  function playheadShot(ctx, time = ctx.time()) {
    const project = ctx.project();
    let found = null, ended = null;
    const hold = !!(project && project.source && project.source.kind === "game");
    for (const track of mainTracks(project)) {
      const event = activeCameraEvent(track, time);
      if (event) { found = { track, event }; continue; }
      const last = hold ? endedCameraEvent(track, time) : null;
      if (last && (!ended || last.start + last.duration > ended.event.start + ended.event.duration)) ended = { track, event: last };
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
    // An added clip whose keys do not own its pose has no source but its own samples: a bake
    // (keys or layers) would build on its last output every time. Nothing is written to it.
    if (shot.user && !shot.owned) return { restore: true };
    const record = shot.record;
    const active = affecting(ctx, shot);
    // A shot whose keys own its pose always bakes (a resized one takes its new grid).
    if ((!record || !record.keys.length) && !active.length) return { restore: true };
    // Layers get copies (they may write into the arrays); a rotation still equal to its
    // untouched source sample is kept as stored, bit for bit.
    const untouched = [];
    const frames = shot.source.map((sample, index) => {
      const pose = basePose(shot, record, index);
      untouched.push(pose.rotation === sample.rotation);
      return { t: shot.event.start + sample.time, position: pose.position.slice(0, 3), rotation: pose.rotation.slice(0, 4), fov: pose.fov };
    });
    for (const layer of active) {
      try { layer.apply(ctx, shot, frames); } catch (error) { console.error(`MV Studio camera layer ${layer.id}`, error); }
    }
    const keyframes = [];
    let previous = null;
    frames.forEach((frame, index) => {
      const sample = shot.source[index];
      // Changed positions stay inside the native writer's range (±1e6 m).
      const position = vector(frame.position, 3)
        ? frame.position.slice(0, 3).map((value, axis) => value === sample.position[axis] ? value : clamp(value, -POSITION_LIMIT, POSITION_LIMIT))
        : sample.position.slice(0, 3);
      let rotation = vector(frame.rotation, 4) ? frame.rotation : sample.rotation;
      const kept = untouched[index] && rotation.slice(0, 4).every((value, axis) => value === sample.rotation[axis]);
      rotation = kept ? sample.rotation.slice(0, 4) : M.normalize(rotation);
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

  // A shot's length is locked while its samples differ from the originals: the native writer
  // keeps the sample count. Shots made in the editor are never written natively and resize.
  function durationLocked(ctx, track, event) {
    if (!mainTrack(track) || !event) return false;
    const original = ctx.history && ctx.history.originals ? ctx.history.originals.get(event.id) : undefined;
    return original !== null && differs(ctx, event);
  }

  // Shots a bake must visit: those with a record, a layer, or samples to restore.
  function candidates(ctx, events) {
    const list = [];
    for (const { track, event } of mainCameraShots(ctx)) {
      if (events && !events.includes(event.id)) continue;
      const shot = shotInfo(ctx, track, event);
      if (!shot || !shot.source || (shot.lengthChanged && !differs(ctx, event))) continue;
      if (shot.record || (shot.user && shot.regrid) || differs(ctx, event) || (layers.length && affecting(ctx, shot).length)) list.push(shot);
    }
    return list;
  }

  function bakeNow(ctx, events) {
    const changed = new Set();
    for (const shot of candidates(ctx, events)) {
      if (writeBake(ctx, shot, bakeShot(ctx, shot))) changed.add(shot.track.id);
    }
    for (const id of changed) { ctx.refreshLane(id); stateOf(ctx).refreshed?.add(id); }
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

  // selection: the keys selected once the edit is applied ({ frames, frame } of this shot,
  // null for none, undefined to keep the selection as it is).
  function commit(ctx, shot, record, label, detail, selection) {
    if (ctx.locked() || !ctx.history) return false;
    const editor = ctx.editor(false);
    const changes = [];
    if (!editor || !editor.camera || editor.camera.version !== 1) changes.push({ target: { kind: "editor" }, path: ["camera", "version"], after: 1 });
    changes.push({ target: { kind: "editor" }, path: ["camera", "shots", shot.event.id], after: record ? cleanRecord(record) : undefined });
    // The edit that claims an added clip (editStart) carries its samples in the same step: the
    // bake writes outside history, and undoing the edit must give the clip back the samples it
    // had (no original holds them).
    if (shot.claimed && record) {
      const baked = bakeShot(ctx, { ...shot, record: normalizeRecord(cleanRecord(record), shot.count) });
      if (baked.keyframes) changes.push({ target: { kind: "event", track: shot.track.id, event: shot.event.id }, path: ["values", "keyframes"], after: baked.keyframes });
    }
    changes.push(...orphanChanges(ctx, shot.event.id));
    // The selection is kept with the record it was made on, before and after the edit, so an
    // undo or redo brings back the keys that were selected then (restoreSelection).
    noteSelection(ctx);
    if (selection !== undefined) setSelection(ctx, selection ? shot.event.id : null, selection ? selection.frames : [], selection && selection.frame);
    const changed = ctx.history.apply({ label, detail: detail || shot.event.label || "", changes });
    noteSelection(ctx);
    return changed;
  }

  // Records whose clip is gone (deleted on the timeline) leave with the next camera command,
  // in the same undo step: undoing it brings them back before the clip's deletion is undone.
  function orphanChanges(ctx, keep) {
    const editor = ctx.editor(false), shots = editor && editor.camera && editor.camera.shots;
    const project = ctx.project();
    if (!shots || typeof shots !== "object" || !project || !Array.isArray(project.tracks)) return [];
    const ids = new Set();
    for (const track of project.tracks) for (const event of Array.isArray(track.events) ? track.events : []) if (event) ids.add(event.id);
    return Object.keys(shots).filter((id) => id !== keep && !ids.has(id))
      .map((id) => ({ target: { kind: "editor" }, path: ["camera", "shots", id], after: undefined }));
  }

  function emptyRecord(ctx) {
    return { mode: "offset", space: stateOf(ctx).space, keys: [] };
  }

  // The shot an edit at `time` applies to and the record it starts from (a copy). An added clip
  // whose keys do not own its pose (Duplicate clip copies the samples, not the keys) has no fixed
  // source: an offset over its samples would build on its own last bake. Its first edit claims
  // it: its motion becomes linear keys (within the simplify tolerance) on its 60 Hz grid, as
  // ensureUserShot starts a shot with keys, and from then on the keys own its pose.
  function editStart(ctx, shot, time) {
    if (!shot.user || shot.owned) return { shot, record: shot.record ? clone(shot.record) : emptyRecord(ctx) };
    const source = userGrid(shot.source, shot.event.duration);
    const grid = { ...shot, source, count: source.length, regrid: source !== shot.source, owned: true, claimed: true, record: null };
    grid.frame = frameAt(grid, time);
    return { shot: grid, record: { mode: "keys", space: "view", keys: motionKeys(grid, null) } };
  }

  // The motion of a shot (its keyed pose, or its samples without a record) as linear keys,
  // kept where the straight line between them leaves 2 mm / 0.05° / 0.01° (M.simplify).
  function motionKeys(shot, record) {
    const samples = [];
    let near = null;
    for (let frame = 0; frame < shot.count; frame++) {
      const value = absoluteOf(basePose(shot, record, frame), near);
      near = value;
      if (!finite(value.fov)) value.fov = shot.fallbackFov;
      samples.push(value);
    }
    return M.simplify(samples).map((frame) => ({ frame, values: { ...samples[frame] }, interp: "linear", handle: "auto-clamped" }));
  }

  function upsertKey(record, frame, values, template) {
    const existing = record.keys.find((key) => key.frame === frame);
    if (existing) { existing.values = values; return existing; }
    const key = { frame, values, interp: template ? template.interp : "bezier", handle: template ? template.handle : "auto-clamped" };
    record.keys.push(key);
    record.keys.sort((a, b) => a.frame - b.frame);
    return key;
  }

  // ---- key selection ----------------------------------------------------------------------------
  // state.selected = { event, frames (sorted), frame }: the selected keys of one shot and the
  // active one (its fields, Bezier handles and keyboard focus). One shot at a time: a record, its
  // frame grid and its mode belong to one shot, so every group command edits one record in one
  // undo step.
  const ONE_SHOT = "Keys can be selected in one camera shot at a time.";

  function setSelection(ctx, eventId, frames, active) {
    const state = stateOf(ctx), previous = state.selected;
    const list = [...new Set((frames || []).filter(Number.isInteger))].sort((a, b) => a - b);
    if (eventId === null || eventId === undefined || !list.length) state.selected = null;
    else {
      const kept = previous && previous.event === eventId && list.includes(previous.frame) ? previous.frame : list[list.length - 1];
      state.selected = { event: eventId, frames: list, frame: list.includes(active) ? active : kept };
    }
    return state.selected;
  }

  function select(ctx, shot, frame) {
    setSelection(ctx, shot ? shot.event.id : null, frame === null || frame === undefined ? [] : [frame], frame);
  }

  // The selected keys the shot's record holds ([] when the selection is in another shot).
  function selectedFrames(ctx, shot) {
    const selected = stateOf(ctx).selected;
    if (!shot || !shot.record || !selected || selected.event !== shot.event.id) return [];
    const held = new Set(shot.record.keys.map((key) => key.frame));
    return selected.frames.filter((frame) => held.has(frame));
  }

  // The shot of the selection and its selected keys, or null.
  function selectionTarget(ctx) {
    const selected = stateOf(ctx).selected;
    const shot = selected ? findShot(ctx, selected.event, ctx.time()) : null;
    const frames = selectedFrames(ctx, shot);
    return frames.length ? { shot, frames } : null;
  }

  // Shift/Ctrl/Cmd+click and Shift+Space: a key joins or leaves the selection. A key of
  // another shot starts a new selection there.
  function toggleKey(ctx, shot, frame) {
    const selected = stateOf(ctx).selected;
    if (selected && selected.event !== shot.event.id) {
      ctx.report(t(ctx, ONE_SHOT));
      return setSelection(ctx, shot.event.id, [frame], frame);
    }
    const frames = selectedFrames(ctx, shot);
    if (frames.includes(frame)) return setSelection(ctx, shot.event.id, frames.filter((item) => item !== frame));
    return setSelection(ctx, shot.event.id, [...frames, frame], frame);
  }

  // Keys found by a box (lane or curve view): { eventId: [frames] } in time order. With add,
  // they join the selection of its shot; otherwise the shot with the most keys in the box wins.
  function selectBoxed(ctx, hits, add) {
    const selected = stateOf(ctx).selected;
    let eventId = null, frames = [];
    if (add && selected) {
      eventId = selected.event;
      frames = [...selectedFrames(ctx, findShot(ctx, eventId)), ...(hits.get(eventId) || [])];
    } else {
      for (const [id, list] of hits) if (list.length > frames.length) { eventId = id; frames = list; }
    }
    if ([...hits.keys()].some((id) => id !== eventId && hits.get(id).length)) ctx.report(t(ctx, ONE_SHOT));
    setSelection(ctx, eventId, frames);
    selectionChanged(ctx);
    return stateOf(ctx).selected;
  }

  function selectAllKeys(ctx, shot = playheadShot(ctx)) {
    if (!shot || !shot.record || !shot.record.keys.length) return false;
    const selected = stateOf(ctx).selected;
    setSelection(ctx, shot.event.id, shot.record.keys.map((key) => key.frame), selected && selected.event === shot.event.id ? selected.frame : undefined);
    selectionChanged(ctx);
    return true;
  }

  function clearSelection(ctx) {
    if (!stateOf(ctx).selected) return false;
    setSelection(ctx, null);
    selectionChanged(ctx);
    return true;
  }

  // "Select several" (for touch, where there is no Shift or Ctrl): while it is on, a tap on a key
  // adds or removes it, a box adds to the selection, and a sideways touch or pen drag on the camera
  // lane draws a box instead of scrolling the timeline (CSS lets only vertical panning and pinch
  // zoom through there; the other lanes and the ruler still scroll sideways).
  function setMulti(ctx, on) {
    const state = stateOf(ctx);
    state.multi = !!on;
    if (global.document) for (const lane of document.querySelectorAll(".mv-lane.mv-cam-lane")) lane.classList.toggle("mv-cam-multi", state.multi);
    renderPanel(ctx);
    return state.multi;
  }

  // After a selection change that is not an edit: remembered, drawn on the diamonds, the panel.
  function selectionChanged(ctx) {
    noteSelection(ctx);
    paintSelection(ctx);
    renderPanel(ctx);
  }

  // The selection made on each record state (its JSON), so undo and redo restore it.
  function recordText(ctx, eventId) {
    const raw = recordOf(ctx, eventId);
    return raw === undefined ? "" : JSON.stringify(raw);
  }

  function noteSelection(ctx) {
    const state = stateOf(ctx), selected = state.selected;
    if (!selected || !ctx.project()) return;
    const key = selected.event + "\n" + recordText(ctx, selected.event);
    state.memory.delete(key);
    state.memory.set(key, { frames: selected.frames.slice(), frame: selected.frame });
    if (state.memory.size > 256) state.memory.delete(state.memory.keys().next().value);
  }

  // After an undo or redo: the selection made on the records the step brought back (the
  // selected shot first), else the selection without the keys that are gone.
  function restoreSelection(ctx, ids) {
    const state = stateOf(ctx), selected = state.selected;
    const order = selected && ids.includes(selected.event) ? [selected.event, ...ids] : ids;
    for (const id of order) {
      const hit = state.memory.get(id + "\n" + recordText(ctx, id));
      if (!hit) continue;
      const shot = findShot(ctx, id);
      const held = new Set(shot && shot.record ? shot.record.keys.map((key) => key.frame) : []);
      const frames = hit.frames.filter((frame) => held.has(frame));
      if (frames.length) { setSelection(ctx, id, frames, hit.frame); return true; }
    }
    if (selected) setSelection(ctx, selected.event, selectedFrames(ctx, findShot(ctx, selected.event)));
    return false;
  }

  // The diamonds on the lanes show the selection (aria-selected for screen readers).
  function paintSelection(ctx) {
    if (!global.document) return;
    const selected = stateOf(ctx).selected;
    for (const diamond of document.querySelectorAll(".mv-cam-key")) {
      const frame = Number(diamond.dataset.frame);
      const on = !!selected && selected.event === diamond.dataset.event && selected.frames.includes(frame);
      if (diamond.getAttribute("aria-selected") !== String(on)) diamond.setAttribute("aria-selected", String(on));
      diamond.classList.toggle("mv-selected", on);
      diamond.classList.toggle("mv-cam-key-active", on && selected.frame === frame);
    }
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

  // A key's values as stored: positions within the native writer's ±1e6 m, and a FOV that keeps
  // the shot's FOV at that frame in [1, 170] (absolute in keys mode, a delta in offset mode).
  function limitValues(shot, record, frame, values) {
    const out = { ...values };
    for (const channel of M.POSITION) if (finite(out[channel])) out[channel] = clamp(out[channel], -POSITION_LIMIT, POSITION_LIMIT);
    if (finite(out.fov)) {
      if (record.mode === "keys") out.fov = clampFov(out.fov);
      else {
        const sample = shot.source[frame], base = finite(sample.fov) ? sample.fov : shot.fallbackFov;
        out.fov = clamp(out.fov, 1 - base, 170 - base);
      }
    }
    return out;
  }

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
    const at = finite(time) ? time : ctx.time();
    const found = requireShot(ctx, playheadShot(ctx, at));
    if (!found) return false;
    const { shot, record } = editStart(ctx, found, at);
    const frame = shot.frame;
    const current = channelValues(shot, record, frame);
    let values;
    if (row === "absolute" && record.mode === "offset") {
      const pose = basePose(shot, record, frame);
      const absolute = absoluteOf(pose, M.quaternionToEulerZXY(shot.source[frame].rotation));
      if (!finite(absolute.fov)) absolute.fov = shot.fallbackFov;
      const groups = new Set(Object.keys(patch).map(groupOf));
      values = deltasFor(shot, record, frame, { ...absolute, ...patch }, groups, current);
    } else values = { ...current, ...patch };
    values = limitValues(shot, record, frame, values);
    upsertKey(record, frame, values);
    const channel = Object.keys(patch)[0];
    showChannel(ctx, channel);
    const changed = commit(ctx, shot, record, "Edit camera key", channel, { frames: [frame], frame });
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
    if (!requireShot(ctx, found)) return false;
    const { shot, record } = editStart(ctx, found, ctx.time());
    const frame = shot.frame;
    const view = viewTarget(ctx, shot, frame);
    if (!view) return false;
    if (view.mode !== "orbit") {
      if (!auto) ctx.report(t(ctx, "Switch the preview camera to Free camera to key the view."), true);
      return false;
    }
    const current = channelValues(shot, record, frame);
    let values;
    if (record.mode === "keys") {
      const euler = M.quaternionToEulerZXY(view.rotation, { pan: current.pan, tilt: current.tilt, roll: current.roll });
      values = { x: view.position[0], y: view.position[1], z: view.position[2], ...euler, fov: clampFov(view.fov) };
    } else {
      values = deltasFor(shot, record, frame, { x: view.position[0], y: view.position[1], z: view.position[2], rotation: view.rotation, fov: view.fov },
        new Set(["position", "rotation", "fov"]), current);
    }
    upsertKey(record, frame, limitValues(shot, record, frame, values));
    const changed = commit(ctx, shot, record, "Key current view", "", { frames: [frame], frame });
    // The playhead lands on the keyed frame, where the game camera now shows the view.
    ctx.seek(frameTime(shot, frame), { audio: false });
    renderPanel(ctx);
    return changed;
  }

  function addKey(ctx) {
    const found = requireShot(ctx, playheadShot(ctx));
    if (!found) return false;
    const { shot, record } = editStart(ctx, found, ctx.time());
    const frame = shot.frame;
    let changed = false;
    // Claiming an added clip is itself the edit, even when its keys already hold this frame.
    if (shot.claimed || !record.keys.some((key) => key.frame === frame)) {
      upsertKey(record, frame, channelValues(shot, record, frame));
      changed = commit(ctx, shot, record, "Add camera key", "", { frames: [frame], frame });
    } else {
      select(ctx, shot, frame);
      noteSelection(ctx);
      ctx.refreshLane(shot.track.id);
    }
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
    const changed = commit(ctx, found.shot, record, "Delete camera key", "", null);
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
    const changed = commit(ctx, shot, record, "Duplicate camera key", "", { frames: [shot.frame], frame: shot.frame });
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
    noteSelection(ctx);
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
    if (frame === from) { select(ctx, shot, frame); noteSelection(ctx); return false; }
    record.keys[index].frame = frame;
    const changed = commit(ctx, shot, record, "Move camera key", "", { frames: [frame], frame });
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
    if (channel && finite(value)) key.values[channel] = limitValues(shot, record, key.frame, { [channel]: value })[channel];
    commit(ctx, shot, record, "Move camera key", channel, { frames: [key.frame], frame: key.frame });
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

  // The keys a key setting applies to: the selected keys when the target key is one of them,
  // else the target key alone.
  function targetKeys(ctx, found) {
    const frames = selectedFrames(ctx, found.shot);
    return frames.includes(found.key.frame) ? frames : [found.key.frame];
  }

  function setKeyProperty(ctx, property, value) {
    const found = targetKey(ctx);
    if (!found || !found.shot.editable) return false;
    const frames = targetKeys(ctx, found);
    if (property === "frame") {
      return !!moveKeys(ctx, found.shot.event.id, frames, Math.round(value) - found.key.frame, { active: found.key.frame });
    }
    if (!(property === "interp" && M.INTERPOLATIONS.includes(value)) && !(property === "handle" && M.HANDLES.includes(value))) return false;
    const record = clone(found.shot.record);
    const chosen = new Set(frames);
    // Free handles start from the handles every key has now, before any key changes.
    const handles = new Map();
    record.keys.forEach((key, index) => {
      if (chosen.has(key.frame) && property === "handle" && value === "free" && key.handle !== "free") {
        handles.set(key, Object.fromEntries(CHANNELS.map((channel) => [channel, M.handles(record.keys, index, channel)])));
      }
    });
    for (const key of record.keys) {
      if (!chosen.has(key.frame)) continue;
      if (property === "interp") { key.interp = value; continue; }
      if (handles.has(key)) key.handles = handles.get(key);
      key.handle = value;
      if (value !== "free") delete key.handles;
    }
    const changed = commit(ctx, found.shot, record, property === "interp" ? "Change interpolation" : "Change handle type");
    renderPanel(ctx);
    return changed;
  }

  // Ease presets on the outgoing segment of each selected key, in time order (a key both ends one
  // segment and starts the next: the later segment's preset wins on it).
  function ease(ctx, preset) {
    const found = targetKey(ctx);
    if (!found || !found.shot.editable || !["linear", "ease-in-out", "ease-in", "ease-out"].includes(preset)) return false;
    const record = clone(found.shot.record);
    const chosen = new Set(targetKeys(ctx, found));
    const handle = (item, type) => { if (item) { item.handle = type; delete item.handles; } };
    record.keys.forEach((key, index) => {
      if (!chosen.has(key.frame)) return;
      const next = record.keys[index + 1];
      if (preset === "linear") { key.interp = "linear"; return; }
      key.interp = "bezier";
      if (preset === "ease-in-out") { handle(key, "flat"); handle(next, "flat"); }
      else if (preset === "ease-in") { handle(key, "flat"); handle(next, "auto-clamped"); }
      else { handle(key, "auto-clamped"); handle(next, "flat"); }
    });
    const changed = commit(ctx, found.shot, record, "Apply ease preset", preset);
    renderPanel(ctx);
    return changed;
  }

  // ---- group edits (the selected keys of one shot, one undo step each) ---------------------------
  // How far a group of keys can move in time: inside the shot, never onto or past a key that is
  // not in the group. Returns { low, high } (frames; low <= 0 <= high).
  function moveBounds(keys, frames, count) {
    const chosen = new Set(frames);
    const all = [...new Set(keys.map((key) => key.frame))].sort((a, b) => a - b);
    let low = -Infinity, high = Infinity, below = null, above = null;
    for (const frame of all) {
      if (!chosen.has(frame)) { below = frame; continue; }
      low = Math.max(low, -frame, below === null ? -Infinity : below + 1 - frame);
      high = Math.min(high, count - 1 - frame);
    }
    for (let index = all.length - 1; index >= 0; index--) {
      const frame = all[index];
      if (!chosen.has(frame)) { above = frame; continue; }
      if (above !== null) high = Math.min(high, above - 1 - frame);
    }
    return { low: Math.min(0, low), high: Math.max(0, high) };
  }

  // A time stretch of a group, scaled around its first key so its last key lands on `target`,
  // each key snapped to a frame and one frame after the previous one at least. When that puts a
  // key on or past a key outside the group, or outside the shot, the target is pulled back toward
  // the last key until it fits. Returns { end, mapping: Map(frame → new frame) } or null.
  function planScale(keys, frames, target, count) {
    const group = [...new Set(frames)].sort((a, b) => a - b);
    if (group.length < 2 || !finite(target)) return null;
    const first = group[0], last = group[group.length - 1], chosen = new Set(group);
    const all = [...new Set(keys.map((key) => key.frame))].sort((a, b) => a - b);
    const map = (end) => {
      const scale = (end - first) / (last - first), mapping = new Map();
      let previous = -Infinity;
      for (const frame of group) {
        const next = Math.max(first + Math.round((frame - first) * scale), previous + 1);
        mapping.set(frame, next);
        previous = next;
      }
      return mapping;
    };
    const fits = (mapping) => {
      let previous = -1;
      for (const frame of all) {
        const next = chosen.has(frame) ? mapping.get(frame) : frame;
        if (next <= previous || next > count - 1) return false;
        previous = next;
      }
      return true;
    };
    const start = Math.max(first + 1, Math.min(Math.round(target), count - 1));
    const step = start > last ? -1 : 1;
    for (let end = start; end !== last; end += step) {
      const mapping = map(end);
      if (fits(mapping)) return { end, mapping };
    }
    return null;
  }

  // Moves keys of a shot by `delta` frames together (clamped by moveBounds) and, for a curve-view
  // drag, adds `change` to one channel of each (free handles are relative and follow). `base` is
  // the record the gesture started from. Returns the frames moved, or false.
  function moveKeys(ctx, eventId, frames, delta, { channel = null, change = 0, base = null, active } = {}) {
    const shot = findShot(ctx, eventId, ctx.time());
    if (!shot || !shot.editable || !shot.record) return false;
    const record = clone(base ? normalizeRecord(base, shot.count) : shot.record);
    const group = [...new Set(frames)].filter((frame) => record.keys.some((key) => key.frame === frame));
    if (!group.length) return false;
    const { low, high } = moveBounds(record.keys, group, shot.count);
    const applied = clamp(Math.round(finite(delta) ? delta : 0), low, high);
    const value = !!channel && CHANNELS.includes(channel) && finite(change);
    const chosen = new Set(group), selected = stateOf(ctx).selected;
    const lead = group.includes(active) ? active : selected && selected.event === eventId && group.includes(selected.frame) ? selected.frame : group[group.length - 1];
    const selection = { frames: group.map((frame) => frame + applied), frame: lead + applied };
    if (!applied && !value && !base) {
      setSelection(ctx, eventId, selection.frames, selection.frame);
      noteSelection(ctx);
      return 0;
    }
    for (const key of record.keys) {
      if (!chosen.has(key.frame)) continue;
      key.frame += applied;
      if (value) key.values[channel] = limitValues(shot, record, key.frame, { [channel]: key.values[channel] + change })[channel];
    }
    record.keys.sort((a, b) => a.frame - b.frame);
    commit(ctx, shot, record, group.length > 1 ? "Move camera keys" : "Move camera key", value ? channel : "", selection);
    renderPanel(ctx);
    return applied;
  }

  // Stretches or compresses the timing of keys around the first of them (planScale). Free
  // handles scale their time offsets with the keys.
  function stretchKeys(ctx, eventId, frames, target) {
    const shot = findShot(ctx, eventId, ctx.time());
    if (!shot || !shot.editable || !shot.record) return false;
    const record = clone(shot.record);
    const group = [...new Set(frames)].filter((frame) => record.keys.some((key) => key.frame === frame)).sort((a, b) => a - b);
    const plan = planScale(record.keys, group, target, shot.count);
    if (!plan) return false;
    const first = group[0], last = group[group.length - 1];
    const scale = (plan.mapping.get(last) - first) / (last - first);
    for (const key of record.keys) {
      if (!plan.mapping.has(key.frame)) continue;
      key.frame = plan.mapping.get(key.frame);
      if (key.handles) for (const pair of Object.values(key.handles)) for (const side of ["in", "out"]) pair[side][0] *= scale;
    }
    record.keys.sort((a, b) => a.frame - b.frame);
    const selected = stateOf(ctx).selected;
    const lead = selected && selected.event === eventId && plan.mapping.has(selected.frame) ? selected.frame : last;
    commit(ctx, shot, record, "Scale camera key timing", `${Math.round(scale * 100)}%`,
      { frames: [...plan.mapping.values()], frame: plan.mapping.get(lead) });
    renderPanel(ctx);
    return plan;
  }

  // The panel's time scale: factor 0.5 = half the spacing, 2 = twice (around the first selected key).
  function scaleKeys(ctx, factor) {
    const target = selectionTarget(ctx);
    if (!target || target.frames.length < 2) { ctx.report(t(ctx, "Select at least two keys to scale their timing."), true); return false; }
    if (!finite(factor) || factor <= 0) return false;
    const { shot, frames } = target, first = frames[0], last = frames[frames.length - 1];
    const wanted = first + Math.round((last - first) * factor);
    if (wanted === last) return false;
    const plan = stretchKeys(ctx, shot.event.id, frames, wanted);
    if (!plan || plan.end !== wanted) ctx.report(t(ctx, "The timing stops at a neighbouring key or the end of the shot."), !plan);
    return plan;
  }

  // Adds the same amount to channels of every selected key ({ x: 0.5, pan: -10, … }; m, °).
  function offsetKeys(ctx, deltas) {
    const target = selectionTarget(ctx);
    if (!target || !target.shot.editable) return false;
    const channels = CHANNELS.filter((channel) => finite(deltas && deltas[channel]) && deltas[channel] !== 0);
    if (!channels.length) return false;
    const { shot, frames } = target, record = clone(shot.record), chosen = new Set(frames);
    for (const key of record.keys) {
      if (!chosen.has(key.frame)) continue;
      const values = { ...key.values };
      for (const channel of channels) values[channel] += deltas[channel];
      key.values = limitValues(shot, record, key.frame, values);
    }
    const changed = commit(ctx, shot, record, "Offset camera keys", channels.join(", "));
    renderPanel(ctx);
    return changed;
  }

  // Deletes the selected keys (or, with none selected, the key under the playhead).
  function deleteKeys(ctx) {
    const target = selectionTarget(ctx);
    if (!target) return deleteKey(ctx);
    if (!target.shot.editable) return false;
    const { shot, frames } = target, record = clone(shot.record), chosen = new Set(frames);
    record.keys = record.keys.filter((key) => !chosen.has(key.frame));
    const changed = commit(ctx, shot, record, frames.length > 1 ? "Delete camera keys" : "Delete camera key", "", null);
    renderPanel(ctx);
    return changed;
  }

  // Copy: the selected keys with their timing relative to the first one, their stored values and
  // the camera pose each one gives (so a paste into a shot of another mode keeps the pose).
  function copyKeys(ctx) {
    const target = selectionTarget(ctx);
    if (!target) return false;
    const { shot, frames } = target, record = shot.record;
    let near = null;
    const keys = frames.map((frame) => {
      const key = record.keys.find((item) => item.frame === frame);
      const pose = absoluteOf(basePose(shot, record, frame), near);
      near = pose;
      if (!finite(pose.fov)) pose.fov = shot.fallbackFov;
      const item = { offset: frame - frames[0], values: { ...key.values }, interp: key.interp, handle: key.handle, pose };
      if (key.handles) item.handles = clone(key.handles);
      return item;
    });
    stateOf(ctx).clipboard = { mode: record.mode, space: record.space, keys };
    ctx.report(format(ctx, "Camera keys copied: {count}.", { count: keys.length }));
    renderPanel(ctx);
    return true;
  }

  // Offset deltas of one space in the other, at a frame of the shot.
  function otherSpace(shot, frame, values, space) {
    const q = M.normalize(shot.source[frame].rotation);
    const moved = space === "world" ? M.rotateVector(q, [-values.x, values.y, -values.z]) : M.rotateVector(M.conjugate(q), [values.x, values.y, values.z]);
    return space === "world" ? { x: moved[0], y: moved[1], z: moved[2] } : { x: -moved[0], y: moved[1], z: -moved[2] };
  }

  // Paste at the playhead (the same or another camera shot): the first copied key lands on the
  // playhead frame, the others keep their spacing, keys past the shot's ends are left out, and a
  // pasted key replaces a key on the same frame. A shot with no keys takes the copied keys' mode;
  // offset keys keep their offsets (turned into the shot's offset space); between offset and
  // keyframe shots the copied camera pose is kept.
  function pasteKeys(ctx, { time } = {}) {
    const clip = stateOf(ctx).clipboard;
    if (!clip || !clip.keys.length) { ctx.report(t(ctx, "Copy camera keys first."), true); return false; }
    const at = finite(time) ? time : ctx.time();
    const found = requireShot(ctx, playheadShot(ctx, at));
    if (!found) return false;
    const { shot, record: start } = editStart(ctx, found, at);
    const record = shot.claimed || shot.record ? start : { mode: clip.mode, space: clip.space, keys: [] };
    const placed = clip.keys.map((key) => ({ key, frame: shot.frame + key.offset })).filter((item) => item.frame >= 0 && item.frame < shot.count);
    if (!placed.length) { ctx.report(t(ctx, "The copied keys do not fit in this shot."), true); return false; }
    const frames = new Set(placed.map((item) => item.frame));
    record.keys = record.keys.filter((key) => !frames.has(key.frame));
    let near = zeros();
    for (const { key, frame } of placed) {
      let values;
      if (record.mode === clip.mode && (record.mode === "keys" || record.space === clip.space)) values = { ...key.values };
      else if (record.mode === "offset" && clip.mode === "offset") values = { ...key.values, ...otherSpace(shot, frame, key.values, record.space) };
      else if (record.mode === "keys") values = { ...key.pose };
      else values = deltasFor(shot, record, frame, key.pose, new Set(["position", "rotation", "fov"]), near);
      near = values;
      const item = { frame, values: limitValues(shot, record, frame, values), interp: key.interp, handle: key.handle };
      if (key.handle === "free" && key.handles) item.handles = clone(key.handles);
      record.keys.push(item);
    }
    record.keys.sort((a, b) => a.frame - b.frame);
    const changed = commit(ctx, shot, record, "Paste camera keys", String(placed.length), { frames: [...frames], frame: placed[0].frame });
    if (placed.length < clip.keys.length) ctx.report(format(ctx, "Keys outside this shot were left out: {count}.", { count: clip.keys.length - placed.length }));
    renderPanel(ctx);
    return changed ? placed.length : false;
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
      const keys = record.keys.map((key) => ({ ...clone(key), values: { ...key.values, ...otherSpace(shot, key.frame, key.values, space) } }));
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
    const found = requireShot(ctx, playheadShot(ctx));
    if (!found || !["original", "offset", "keys"].includes(mode)) return false;
    const current = found.record ? found.record.mode : "original";
    if (current === mode) return false;
    if (found.user && mode !== "keys") return false;
    const lossy = (current === "offset" && found.record.keys.length) || current === "keys" || (mode === "keys");
    if (confirm && lossy && typeof global.confirm === "function" && !global.confirm(t(ctx, CONFIRM[mode]))) { renderPanel(ctx, true); return false; }
    // An added clip converts on the grid its keys will own (editStart), from its samples.
    const shot = editStart(ctx, found, ctx.time()).shot;
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
    const found = requireShot(ctx, playheadShot(ctx));
    if (!found) return false;
    // An added clip converts on the grid its keys will own (editStart), from its samples.
    const shot = editStart(ctx, found, ctx.time()).shot;
    const keys = motionKeys(shot, shot.record);
    const record = { mode: "keys", space: shot.record ? shot.record.space : stateOf(ctx).space, keys };
    const changed = commit(ctx, shot, record, "Convert to keyframes", String(keys.length));
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
    noteSelection(ctx);
    const changed = ctx.history.apply({ label: "Revert shot", detail: event.label || "", changes });
    if (stateOf(ctx).selected && stateOf(ctx).selected.event === event.id) setSelection(ctx, null);
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
    // An id the project never held, as the host's Duplicate clip picks one: not a deleted clip's
    // (editor.originals keeps it), nor one a camera record is kept under.
    const ids = new Set(project.tracks.flatMap((item) => item.events.map((event) => event.id)));
    const used = (id) => ids.has(id) || recordOf(ctx, id) !== undefined || ctx.history.originals.get(id) !== undefined;
    let number = 1;
    while (used(`${track.id}:u${number}`)) number++;
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
    changes.push(...orphanChanges(ctx, id));
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
  // The diamonds of a lane are the options of one multi-select list box (aria-selected), so a
  // screen reader hears which keys are selected.
  function decorate(ctx, track, lane, layout) {
    if (!mainTrack(track) || !global.document) return;
    attachLane(ctx, lane);
    lane.classList.toggle("mv-cam-multi", stateOf(ctx).multi);
    const selected = stateOf(ctx).selected;
    let list = null;
    for (const event of track.events) {
      const shot = shotInfo(ctx, track, event);
      if (!shot || !shot.record || !shot.record.keys.length) continue;
      for (const key of shot.record.keys) {
        const time = frameTime(shot, key.frame);
        const on = !!selected && selected.event === event.id && selected.frames.includes(key.frame);
        const label = format(ctx, "Key {time}", { time: formatTime(time) });
        const diamond = ctx.make("button", null, { type: "button", class: "mv-key mv-cam-key", role: "option", "data-event": event.id,
          "data-frame": String(key.frame), "aria-label": label, title: label, "aria-selected": String(on) });
        diamond.style.left = `${time * layout.pixelsPerSecond}px`;
        diamond.style.setProperty("--mv-clip-row", layout.rowOf.get(event.id) || 0);
        if (on) diamond.classList.add("mv-selected");
        if (on && selected.frame === key.frame) diamond.classList.add("mv-cam-key-active");
        attachDiamond(ctx, diamond, shot.event.id, key.frame, layout);
        if (!list) {
          list = ctx.make("div", null, { class: "mv-cam-keylist", role: "listbox", "aria-multiselectable": "true",
            "aria-orientation": "horizontal", "aria-label": t(ctx, "Camera keys") });
          lane.append(list);
        }
        list.append(diamond);
      }
    }
  }

  // Keys pressed on a key (a lane diamond or a curve-view point); true when handled.
  // Shift+Space / Shift+Enter add or remove the key; ←/→ (also with Alt; Shift: 10 frames) move
  // the selection, or this key alone when it is not selected; Delete removes the selection.
  function keyOnKey(ctx, event, shot, frame, refocus) {
    const key = shortcutKey(event), command = event.ctrlKey || event.metaKey;
    if (!command && !event.altKey && event.shiftKey && (key === " " || key === "enter")) {
      toggleKey(ctx, shot, frame);
      selectionChanged(ctx);
      return true;
    }
    if (!command && (key === "arrowleft" || key === "arrowright")) {
      if (ctx.locked()) return true;
      let frames = selectedFrames(ctx, shot);
      if (!frames.includes(frame)) frames = [frame];
      const step = (key === "arrowleft" ? -1 : 1) * (event.shiftKey ? 10 : 1);
      const moved = moveKeys(ctx, shot.event.id, frames, step, { active: frame });
      if (moved) {
        const now = findShot(ctx, shot.event.id);
        if (now) ctx.seek(frameTime(now, frame + moved), { audio: false });
        refocus(frame + moved);
      }
      return true;   // owned even when refused: Alt+← is the browser's Back otherwise
    }
    if (!command && !event.altKey && (key === "delete" || key === "backspace")) {
      if (!selectedFrames(ctx, shot).includes(frame)) select(ctx, shot, frame);
      deleteKeys(ctx);
      return true;
    }
    return selectionShortcut(ctx, event, shot);
  }

  // Ctrl/Cmd+A (all keys of the shot), Ctrl/Cmd+C, Ctrl/Cmd+V and Escape while the camera lane
  // or the curve view has the focus; true when handled.
  function selectionShortcut(ctx, event, shot) {
    const key = shortcutKey(event);
    const command = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey;
    if (command && key === "a") { selectAllKeys(ctx, shot); return true; }
    if (command && key === "c") return copyKeys(ctx);
    if (command && key === "v" && stateOf(ctx).clipboard) { pasteKeys(ctx); return true; }
    if (!command && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey && key === "escape") return clearSelection(ctx);
    return false;
  }

  // Once per lane element: shortcuts on its clips, and box selection by dragging on empty lane
  // space (Shift: added to the selection; Shift+drag also starts on a shot, which then does not
  // move). Touch and pen draw a box only in "Select several" (setMulti), from anywhere on the lane
  // but a key, and the box then adds to the selection; otherwise they scroll the timeline.
  function attachLane(ctx, lane) {
    if (lane.mvCameraKeys) return;
    lane.mvCameraKeys = true;
    lane.classList.add("mv-cam-lane");
    lane.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.isComposing || ctx.locked() || event.target.closest?.(".mv-cam-key")) return;
      const clip = event.target.closest?.(".mv-clip");
      const shot = clip ? findShot(ctx, clip.dataset.event) : null;
      if (shot && selectionShortcut(ctx, event, shot)) { event.preventDefault(); event.stopPropagation(); }
    });
    let box = null, swallow = false;
    lane.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !event.isPrimary || ctx.locked()) return;
      const multi = stateOf(ctx).multi;
      if ((event.pointerType === "touch" || event.pointerType === "pen") && !multi) return;
      const target = event.target;
      if (target.closest?.(".mv-cam-key")) return;
      const onClip = !!target.closest?.(".mv-clip");
      if (onClip ? !(event.shiftKey || multi) : target !== lane && !target.classList?.contains("mv-cam-keylist")) return;
      if (onClip) event.stopPropagation();
      box = { id: event.pointerId, x: event.clientX, y: event.clientY, add: event.shiftKey || multi, element: null };
    }, true);
    lane.addEventListener("pointermove", (event) => {
      if (!box || box.id !== event.pointerId) return;
      if (!box.element) {
        if (Math.hypot(event.clientX - box.x, event.clientY - box.y) < 4) return;
        try { lane.setPointerCapture(event.pointerId); } catch (_) {}
        box.element = ctx.make("div", null, { class: "mv-cam-box", "aria-hidden": "true" });
        lane.append(box.element);
      }
      // The box spans whole clip rows (the rows it crosses): a sideways finger drag gives next to no
      // height, and still takes the keys of the row it runs along.
      const rect = lane.getBoundingClientRect(), height = lane.mvLayout ? lane.mvLayout.rowHeight : 30;
      const rows = Math.max(1, Math.round(rect.height / height));
      const row = (y) => clamp(Math.floor((y - rect.top) / height), 0, rows - 1);
      const left = Math.min(box.x, event.clientX), right = Math.max(box.x, event.clientX);
      const first = row(Math.min(box.y, event.clientY)), last = row(Math.max(box.y, event.clientY));
      const top = first * height, bottom = Math.min(rect.height, (last + 1) * height);
      Object.assign(box.element.style, { left: `${left - rect.left}px`, top: `${top}px`, width: `${right - left}px`, height: `${bottom - top}px` });
      box.rect = { left, right, first, last };
    });
    const finish = (event) => {
      if (!box || box.id !== event.pointerId) return;
      const ended = box;
      box = null;
      if (!ended.element) return;
      ended.element.remove();
      if (event.type !== "pointerup" || !ended.rect) return;
      swallow = true;
      setTimeout(() => { swallow = false; }, 0);
      // A key is inside when its time is and its clip row is one the box spans.
      const hits = new Map();
      for (const diamond of lane.querySelectorAll(".mv-cam-key")) {
        const shape = diamond.getBoundingClientRect(), x = shape.left + shape.width / 2;
        const row = Number(diamond.style.getPropertyValue("--mv-clip-row")) || 0;
        if (x < ended.rect.left || x > ended.rect.right || row < ended.rect.first || row > ended.rect.last) continue;
        if (!hits.has(diamond.dataset.event)) hits.set(diamond.dataset.event, []);
        hits.get(diamond.dataset.event).push(Number(diamond.dataset.frame));
      }
      selectBoxed(ctx, hits, ended.add);
    };
    lane.addEventListener("pointerup", finish);
    lane.addEventListener("pointercancel", finish);
    // Only the lane's own capture: a touch starts captured to the shot under it, which loses that
    // capture (and the event bubbles here) when the lane takes it over.
    lane.addEventListener("lostpointercapture", (event) => {
      if (event.target === lane && box && box.element) finish({ type: "pointercancel", pointerId: event.pointerId });
    });
    // A box drag is not a click: the lane would seek, a shot would be chosen.
    lane.addEventListener("click", (event) => {
      if (!swallow) return;
      swallow = false;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
  }

  // Lane diamonds: a click selects one key (Shift/Ctrl/Cmd+click, or a tap in "Select several",
  // adds or removes it); a drag moves the selected keys together (a key outside the selection
  // moves alone); Alt+drag on the last selected key stretches the selection's timing around its
  // first key. A touch or pen long-press (HOLD_MS, still) turns "Select several" on and adds the key.
  const HOLD_MS = 500;
  function attachDiamond(ctx, diamond, eventId, frame, layout) {
    let drag = null, keyboardToggle = false;
    const pps = () => layout.pixelsPerSecond;
    const laneOf = () => diamond.closest?.(".mv-lane");
    // The dragged key's frame under the pointer: playhead snap within 6 px (Alt: frames only).
    const locate = (event, shot) => {
      let time = frameTime(shot, frame) + (event.clientX - drag.x) / pps();
      if (!event.altKey && Math.abs(ctx.time() - time) * pps() <= 6) time = ctx.time();
      return clamp(Math.round((time - shot.event.start) * FRAME_RATE), 0, shot.count - 1);
    };
    // Preview: every key of the group at its new place.
    const place = (shot, mapping) => {
      const lane = laneOf();
      for (const [from, to] of mapping) {
        const element = from === frame ? diamond : lane?.querySelector(`.mv-cam-key[data-event="${CSS.escape(eventId)}"][data-frame="${from}"]`);
        if (!element) continue;
        element.style.left = `${frameTime(shot, to) * pps()}px`;
        element.classList.add("mv-dragging");
      }
    };
    const hold = () => {
      if (!drag || drag.moved) return;
      drag.held = true;
      const shot = findShot(ctx, eventId);
      if (!shot) return;
      if (!stateOf(ctx).multi) setMulti(ctx, true);
      if (!selectedFrames(ctx, shot).includes(frame)) toggleKey(ctx, shot, frame);
      selectionChanged(ctx);
    };
    diamond.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || ctx.locked()) return;
      event.stopPropagation();
      const touch = event.pointerType === "touch" || event.pointerType === "pen";
      drag = { x: event.clientX, id: event.pointerId, moved: false, touch, alt: event.altKey,
        toggle: event.shiftKey || event.ctrlKey || event.metaKey || stateOf(ctx).multi };
      if (touch) drag.timer = setTimeout(hold, HOLD_MS);
      diamond.setPointerCapture?.(event.pointerId);
    });
    // A finger wobbles: a touch drag starts past 8 px (a mouse past 3).
    diamond.addEventListener("pointermove", (event) => {
      if (!drag || drag.id !== event.pointerId || drag.held) return;
      if (!drag.moved && Math.abs(event.clientX - drag.x) < (drag.touch ? 8 : 3)) return;
      clearTimeout(drag.timer);
      const shot = findShot(ctx, eventId);
      if (!shot || !shot.record) return;
      if (!drag.moved) {
        drag.moved = true;
        const frames = selectedFrames(ctx, shot);
        drag.frames = frames.includes(frame) ? frames : [frame];
        drag.stretch = drag.alt && drag.frames.length > 1 && frame === drag.frames[drag.frames.length - 1];
      }
      const target = locate(event, shot);
      if (drag.stretch) {
        drag.plan = planScale(shot.record.keys, drag.frames, target, shot.count);
        place(shot, drag.plan ? drag.plan.mapping : new Map(drag.frames.map((item) => [item, item])));
      } else {
        const { low, high } = moveBounds(shot.record.keys, drag.frames, shot.count);
        drag.delta = clamp(target - frame, low, high);
        place(shot, new Map(drag.frames.map((item) => [item, item + drag.delta])));
      }
    });
    const finish = (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      const ended = drag;
      drag = null;
      clearTimeout(ended.timer);
      for (const element of laneOf()?.querySelectorAll(".mv-cam-key.mv-dragging") || []) element.classList.remove("mv-dragging");
      diamond.classList.remove("mv-dragging");
      if (event.type === "pointercancel") { ctx.refreshLane(laneOf()?.dataset.track); return; }
      const shot = findShot(ctx, eventId);
      if (!shot) return;
      let at = frame;
      if (ended.held) {
        // The long-press did its work (selectionChanged); the release only redraws.
      } else if (ended.moved && ended.stretch && ended.plan) {
        stretchKeys(ctx, eventId, ended.frames, ended.plan.end);
        at = ended.plan.mapping.get(frame);
      } else if (ended.moved && ended.delta) {
        at = frame + (moveKeys(ctx, eventId, ended.frames, ended.delta, { active: frame }) || 0);
      } else if (ended.toggle && !ended.moved) {
        toggleKey(ctx, shot, frame);
        noteSelection(ctx);
      } else if (!ended.moved || !selectedFrames(ctx, shot).includes(frame)) {
        select(ctx, shot, frame);
        noteSelection(ctx);
      }
      if (!ended.held && (!ended.toggle || ended.moved)) ctx.seek(frameTime(findShot(ctx, eventId) || shot, at), { audio: false });
      ctx.refreshLane(shot.track.id);
      renderPanel(ctx);
      focusDiamond(shot.track.id, eventId, at);
    };
    diamond.addEventListener("pointerup", finish);
    diamond.addEventListener("pointercancel", finish);
    // A long-press is the selection gesture, not a context menu.
    diamond.addEventListener("contextmenu", (event) => event.preventDefault());
    diamond.addEventListener("click", (event) => {
      event.stopPropagation();
      // Keyboard activation (pointer clicks were handled on release); Shift+Enter/Space toggled.
      if (event.detail !== 0) return;
      if (keyboardToggle) { keyboardToggle = false; return; }
      const shot = findShot(ctx, eventId);
      if (!shot) return;
      select(ctx, shot, frame);
      noteSelection(ctx);
      ctx.seek(frameTime(shot, frame), { audio: false });
      ctx.refreshLane(shot.track.id);
      renderPanel(ctx);
      focusDiamond(shot.track.id, eventId, frame);
    });
    diamond.addEventListener("keydown", (event) => {
      // Undo/redo is the host's shortcut (on the document, after this): the diamond is noted
      // first, since the host may redraw the lane before projectChanged runs.
      const key = String(event.key || "").toLowerCase();
      if ((event.ctrlKey || event.metaKey) && !event.altKey && (key === "z" || key === "y")) { noteKeyFocus(ctx, eventId, frame); return; }
      if (event.isComposing) return;
      const shot = findShot(ctx, eventId);
      if (!shot) return;
      if (keyOnKey(ctx, event, shot, frame, (moved) => focusDiamond(shot.track.id, eventId, moved))) {
        if (event.shiftKey && (key === " " || key === "enter")) keyboardToggle = true;
        event.preventDefault();
        event.stopPropagation();
      }
    });
    diamond.addEventListener("keyup", () => { if (keyboardToggle) setTimeout(() => { keyboardToggle = false; }, 0); });
  }

  // A lane refresh replaces the diamonds, and the host then hands the focus to the clip with
  // the same data-event: the selected key's diamond takes it back, so the arrow keys keep moving
  // the keys, not the shot.
  function focusDiamond(trackId, eventId, frame) {
    if (!global.document || typeof CSS === "undefined") return;
    const lane = document.querySelector(`.mv-lane[data-track="${CSS.escape(trackId)}"]`);
    lane?.querySelector(`.mv-cam-key[data-event="${CSS.escape(eventId)}"][data-frame="${frame}"]`)?.focus({ preventScroll: true });
  }

  // The key diamond that has the focus: the one an undo/redo shortcut was pressed on (noted for
  // the length of that key press), else document.activeElement.
  function noteKeyFocus(ctx, eventId, frame) {
    const state = stateOf(ctx), note = { event: eventId, frame };
    state.keyFocus = note;
    setTimeout(() => { if (state.keyFocus === note) state.keyFocus = null; }, 0);
  }

  function focusedKey(ctx) {
    const noted = stateOf(ctx).keyFocus;
    if (noted) return noted;
    const element = global.document && document.activeElement;
    return element && element.classList && element.classList.contains("mv-cam-key")
      ? { event: element.dataset.event, frame: Number(element.dataset.frame) } : null;
  }

  // After an undo or redo with a key diamond focused, the lane redraws hand the focus to the
  // clip: the same key's diamond takes it back, so the arrow keys keep moving keys. When that key
  // is gone (its move was undone), the active key of the restored selection takes the focus, else
  // the nearest key of the same shot takes the focus and the selection.
  function refocusKey(ctx, focused) {
    const shot = findShot(ctx, focused.event);
    const keys = shot && shot.record ? shot.record.keys : [];
    if (!keys.length) return;
    let key = keys.find((item) => item.frame === focused.frame);
    const selected = stateOf(ctx).selected;
    if (!key && selected && selected.event === shot.event.id) key = keys.find((item) => item.frame === selected.frame);
    if (!key) {
      key = keys.reduce((best, item) => Math.abs(item.frame - focused.frame) < Math.abs(best.frame - focused.frame) ? item : best);
      select(ctx, shot, key.frame);
      noteSelection(ctx);
      ctx.refreshLane(shot.track.id);
      renderPanel(ctx);
    }
    focusDiamond(shot.track.id, shot.event.id, key.frame);
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
  const SELECTION_HINT = "Shift or Ctrl+click adds a key. Drag on empty lane or graph space to box-select (Shift adds). Drag a selected key to move them all; Alt+drag the last one to stretch.";
  const TOUCH_HINT = "Touch: turn on Select several (or long-press a key) and tap keys; drag sideways on the camera lane or on the graph to box-select. Drag a selected key to move them all.";
  const MULTI_TITLE = "While this is on, a tap adds or removes a key and a sideways drag on the camera lane selects the keys in a box. A long-press on a key also turns it on.";
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
      // The field then shows the value as stored (clamped), even while it keeps the focus.
      const state = stateOf(ctx);
      state.echo = name;
      try { onChange(input.valueAsNumber); syncPanel(ctx); } finally { state.echo = null; }
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

  // What the built panel depends on: a change rebuilds it (syncPanel only refreshes values).
  // The UI language is part of it, so a language switch rebuilds every label.
  function signature(ctx, shot) {
    const language = [global.document && document.documentElement ? document.documentElement.lang : "", t(ctx, "Camera editor")].join("/");
    if (!shot) return ["none", ctx.project() ? ctx.project().nativeTimeline === true : "", ctx.locked(), language].join("|");
    return [shot.event.id, shot.editable, shot.record ? shot.record.mode : "original", shot.record ? shot.record.space : "", shot.user,
      ctx.locked(), language].join("|");
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
    // A shot added on the timeline only has keys: its first edit turns its motion into keys.
    const mode = shot.user ? "keys" : shot.record ? shot.record.mode : "original";
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
    refs.remove = tool("mv-cam-delete-key", "Delete key", "Delete", () => deleteKeys(ctx));
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

    // Key selection: commands on every selected key, one undo step each. Right under the key tools,
    // so on a phone (the panel stacked over the timeline) it is in reach while tapping keys; the
    // commands that need a selection, the time scale and the offset show while keys are selected.
    {
      const box = ctx.make("fieldset", null, { class: "mv-cam-selection", id: "mv-cam-selection" });
      box.append(ctx.make("legend", t(ctx, "Key selection")));
      refs.selectionCount = ctx.make("p", null, { class: "mv-cam-selection-count", id: "mv-cam-selection-count", "aria-live": "polite" });
      const tools = ctx.make("div", null, { class: "mv-cam-toolbar", role: "group", "aria-label": t(ctx, "Key selection") });
      const action = (id, label, shortcut, run) => {
        const control = ctx.button(t(ctx, label), run, { id, class: "mv-cam-tool", title: `${t(ctx, label)} (${shortcut})` });
        control.setAttribute("aria-keyshortcuts", shortcut.replace("Ctrl/Cmd+", "Control+").replace("Esc", "Escape"));
        tools.append(control);
        return control;
      };
      refs.multi = ctx.button(t(ctx, "Select several"), () => setMulti(ctx, !stateOf(ctx).multi),
        { id: "mv-cam-multi", class: "mv-cam-tool mv-cam-multi-toggle", title: t(ctx, MULTI_TITLE), "aria-pressed": String(state.multi) });
      tools.append(refs.multi);
      refs.selectAll = action("mv-cam-select-all", "Select all keys", "Ctrl/Cmd+A", () => selectAllKeys(ctx));
      refs.clearSelection = action("mv-cam-clear-selection", "Clear selection", "Esc", () => clearSelection(ctx));
      refs.deleteSelected = action("mv-cam-delete-keys", "Delete selected keys", "Delete", () => deleteKeys(ctx));
      refs.copy = action("mv-cam-copy-keys", "Copy keys", "Ctrl/Cmd+C", () => copyKeys(ctx));
      refs.paste = action("mv-cam-paste-keys", "Paste keys", "Ctrl/Cmd+V", () => pasteKeys(ctx));
      const enter = (input, run) => input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); run(); }
      });
      // Time scale around the first selected key.
      const scaleRow = ctx.make("div", null, { class: "mv-cam-batch-row" });
      const scaleLabel = ctx.make("label", null, { class: "mv-cam-number" });
      refs.scale = ctx.make("input", null, { type: "number", id: "mv-cam-scale", min: "1", step: "10", value: "100", "aria-label": t(ctx, "Time scale (%)") });
      scaleLabel.append(ctx.make("span", t(ctx, "Time scale (%)")), refs.scale);
      const scaleNow = () => { const value = refs.scale.valueAsNumber; if (finite(value) && value > 0) scaleKeys(ctx, value / 100); };
      refs.scaleApply = ctx.button(t(ctx, "Scale timing"), scaleNow, { id: "mv-cam-scale-apply", class: "mv-cam-tool",
        title: t(ctx, "Scales the spacing of the selected keys around the first selected key (Alt+drag the last selected key on the timeline does the same).") });
      enter(refs.scale, scaleNow);
      scaleRow.append(scaleLabel, refs.scaleApply);
      // The same amount added to every selected key.
      const offsets = ctx.make("div", null, { class: "mv-cam-row mv-cam-deltas" });
      offsets.append(ctx.make("p", t(ctx, "Add to selected keys"), { class: "mv-cam-row-title" }));
      refs.deltas = {};
      const offsetNow = () => {
        const deltas = {};
        for (const [channel, input] of Object.entries(refs.deltas)) if (input.value !== "" && finite(input.valueAsNumber)) deltas[channel] = input.valueAsNumber;
        if (offsetKeys(ctx, deltas)) for (const input of Object.values(refs.deltas)) input.value = "";
      };
      const space = shot.record ? shot.record.space : state.space;
      for (const set of [M.POSITION, M.ROTATION, ["fov"]]) {
        const line = ctx.make("div", null, { class: "mv-cam-vector" });
        for (const channel of set) {
          const name = mode === "offset" && M.POSITION.includes(channel) && space === "view" ? VIEW_LABELS[channel] : LABELS[channel];
          // The unit (m, °) shows in the empty box and in the name read out.
          const unit = M.POSITION.includes(channel) ? "m" : "°", text = `Δ${t(ctx, name)}`;
          const input = ctx.make("input", null, { type: "number", step: String(STEP[channel]), placeholder: unit === "m" ? "0 m" : "0°",
            id: `mv-cam-delta-${channel}`, "data-mv-cam-delta": channel, "aria-label": `${text} (${unit})`, title: `${text} (${unit})` });
          enter(input, offsetNow);
          const wrap = ctx.make("label", null, { class: "mv-cam-number" });
          wrap.append(ctx.make("span", text), input);
          line.append(wrap);
          refs.deltas[channel] = input;
        }
        offsets.append(line);
      }
      refs.offsetApply = ctx.button(t(ctx, "Apply offset"), offsetNow, { id: "mv-cam-offset-apply", class: "mv-cam-tool" });
      offsets.append(refs.offsetApply);
      refs.batch = ctx.make("div", null, { class: "mv-cam-batch", id: "mv-cam-batch" });
      refs.batch.append(scaleRow, offsets);
      // The hint for the pointer in hand (CSS: a coarse pointer gets the touch one).
      box.append(refs.selectionCount, tools, refs.batch, ctx.make("p", t(ctx, SELECTION_HINT), { class: "mv-field-note mv-cam-selection-hint mv-cam-hint-mouse" }),
        ctx.make("p", t(ctx, TOUCH_HINT), { class: "mv-field-note mv-cam-selection-hint mv-cam-hint-touch" }));
      for (const control of box.querySelectorAll("input, button")) control.disabled = locked;
      root.append(box);
    }

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
      view.addEventListener("keydown", (event) => curveKeydown(ctx, event));
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
      // A click selects one key and seeks to it; Shift/Ctrl/Cmd+click (and Shift+Space), or a tap
      // in "Select several", adds or removes it.
      onSelectKey(frame, { toggle = false } = {}) {
        const shot = playheadShot(ctx);
        if (!shot) return;
        if (toggle || stateOf(ctx).multi) toggleKey(ctx, shot, frame);
        else {
          select(ctx, shot, frame);
          ctx.seek(frameTime(shot, frame), { audio: false });
        }
        noteSelection(ctx);
        ctx.refreshLane(shot.track.id);
        renderPanel(ctx);
      },
      // A box dragged on the plot (added to the selection with Shift or in "Select several").
      onSelectKeys(frames, { add = false } = {}) {
        const shot = playheadShot(ctx);
        if (shot) selectBoxed(ctx, new Map([[shot.event.id, frames]]), add || stateOf(ctx).multi);
      },
      onSeek(frame) {
        const shot = playheadShot(ctx);
        if (shot) ctx.seek(frameTime(shot, frame), { audio: false });
      },
      // Dragging a selected key moves every selected key by the same frames and changes the
      // dragged channel of each by the same amount (one undo step); an unselected key moves alone.
      onDragKey(phase, { from, frame, channel, value }) {
        if (phase === "begin") {
          const shot = playheadShot(ctx);
          const key = shot && shot.record && shot.record.keys.find((item) => item.frame === from);
          if (!key) return null;
          const frames = selectedFrames(ctx, shot);
          dragging = { event: shot.event.id, from, current: from, frames: frames.includes(from) ? frames : [from], base: clone(shot.record),
            channel: null, value: null };
          begin(dragging.frames.length > 1 ? "Move camera keys" : "Move camera key");
          return from;
        }
        if (phase === "end") {
          end();
          const done = dragging;
          dragging = null;
          const shot = done && findShot(ctx, done.event);
          if (shot) ctx.refreshLane(shot.track.id);
          return null;
        }
        if (!dragging) return null;
        const key = dragging.base.keys.find((item) => item.frame === dragging.from);
        const change = channel && finite(value) && key ? value - key.values[channel] : 0;
        const moved = moveKeys(ctx, dragging.event, dragging.frames, finite(frame) ? Math.round(frame) - dragging.from : 0,
          { channel, change, base: dragging.base, active: dragging.from });
        if (moved !== false) dragging.current = dragging.from + moved;
        return dragging.current;
      },
      onDragHandle(phase, { frame, channel, side, handle }) {
        if (phase === "begin") { begin("Edit camera handle"); return; }
        if (phase === "end") { end(); return; }
        const shot = playheadShot(ctx);
        if (shot) setHandle(ctx, shot.event.id, frame, channel, side, handle);
      },
    };
  }

  // Keys pressed in the curve view (the points are its focusable keys).
  function curveKeydown(ctx, event) {
    if (event.defaultPrevented || event.isComposing || ctx.locked()) return;
    const shot = playheadShot(ctx);
    if (!shot) return;
    const target = event.target, point = target.classList?.contains("mv-cam-curve-key") ? Number(target.dataset.frame) : null;
    const channel = point === null ? null : target.dataset.channel;
    const refocus = (frame) => document.querySelector(`#mv-cam-curves .mv-cam-curve-key[data-frame="${frame}"][data-channel="${channel}"]`)?.focus({ preventScroll: true });
    const handled = point === null ? selectionShortcut(ctx, event, shot) : keyOnKey(ctx, event, shot, point, refocus);
    if (handled) { event.preventDefault(); event.stopPropagation(); }
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

  // Text the panel rewrites while the MV plays: the existing text node is written in place.
  // A replaced node is a child-list change, which restyles the whole page through its :has() rules.
  function setText(node, value) {
    const text = node.firstChild;
    if (text && text === node.lastChild && text.nodeType === 3) {
      if (text.data !== value) text.data = value;
    } else if (node.textContent !== value) node.textContent = value;
  }

  // denseCurves of the last shot drawn, while its inputs are the same objects (the bake writes
  // new keyframe arrays; nothing changes them in place).
  function denseCurvesOf(ctx, shot, channels) {
    const state = stateOf(ctx), record = shot.record, values = shot.event.values;
    const key = [shot.event, values, values && values.keyframes, shot.source, shot.count, record ? record.mode : null,
      record ? record.space : null, shot.fallbackFov, channels.join(",")];
    const cached = state.dense;
    if (cached && cached.key.length === key.length && cached.key.every((item, index) => Object.is(item, key[index]))) return cached.value;
    const value = denseCurves(ctx, shot, channels);
    state.dense = { key, value };
    return value;
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
      setText(refs.header, [format(ctx, "Shot {index} / {count}", { index: shot.index + 1, count: shot.total }), shot.event.label || "",
        format(ctx, "Frame {frame} / {last}", { frame, last: shot.count - 1 }) + ` (${formatTime(frameTime(shot, frame) - shot.event.start)})`]
        .filter(Boolean).join(" · "));
    }
    if (!shot.editable) return;
    const record = shot.record;
    const focused = global.document && document.activeElement;
    const put = (name, value, digits) => {
      const input = refs.inputs[name];
      if (input && (input !== focused || state.echo === name)) input.value = round(value, digits);
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
      // Shot-local, the clock of the header's "(0:00.50)".
      if (refs.keyTime) setText(refs.keyTime, formatTime(frameTime(shot, key.frame) - shot.event.start));
      if (refs.interp && refs.interp !== focused) refs.interp.value = key.interp;
      if (refs.handle && refs.handle !== focused) refs.handle.value = key.handle;
    }
    const keys = record ? record.keys : [];
    const chosen = selectionTarget(ctx), count = chosen ? chosen.frames.length : 0, locked = ctx.locked();
    if (refs.selectionCount) {
      setText(refs.selectionCount, !count ? t(ctx, "No keys selected") : chosen.shot.event === shot.event
        ? format(ctx, "Keys selected: {count}", { count }) : format(ctx, "Keys selected in shot {index}: {count}", { count, index: chosen.shot.index + 1 }));
      refs.multi.setAttribute("aria-pressed", String(state.multi));
      refs.selectAll.disabled = !keys.length;
      refs.clearSelection.hidden = refs.deleteSelected.hidden = refs.copy.hidden = refs.batch.hidden = !count;
      refs.clearSelection.disabled = refs.copy.disabled = !count;
      refs.deleteSelected.disabled = locked || !count;
      refs.paste.disabled = locked || !(state.clipboard && state.clipboard.keys.length);
      refs.scale.disabled = refs.scaleApply.disabled = locked || count < 2;
      for (const input of Object.values(refs.deltas)) input.disabled = locked || !count;
      refs.offsetApply.disabled = locked || !count;
    }
    if (refs.remove) refs.remove.disabled = locked || !(count || key || atKey);
    if (refs.duplicate) refs.duplicate.disabled = ctx.locked() || !key || key.frame === frame;
    if (refs.previous) refs.previous.disabled = !keys.some((item) => item.frame < frame);
    if (refs.next) refs.next.disabled = !keys.some((item) => item.frame > frame);
    if (refs.revert) refs.revert.disabled = ctx.locked() || !(record || ctx.edited(shot.event.id));
    if (refs.chips) for (const chip of refs.chips.children) {
      const pressed = String(state.channels.includes(chip.dataset.mvCamChannel));
      if (chip.getAttribute("aria-pressed") !== pressed) chip.setAttribute("aria-pressed", pressed);
    }
    if (refs.curves) {
      refs.curves.update({ count: shot.count, keys, mode: record ? record.mode : "original", channels: state.channels,
        dense: denseCurvesOf(ctx, shot, state.channels), playhead: (ctx.time() - shot.event.start) * FRAME_RATE,
        selected: key ? key.frame : null, selection: selectedFrames(ctx, shot), labels: Object.fromEntries(CHANNELS.map((channel) => [channel, t(ctx, LABELS[channel])])) });
    }
    if (refs.note) {
      const notes = [];
      if (layers.length && affecting(ctx, shot).length) notes.push(t(ctx, "A camera rig also moves this shot."));
      if (durationLocked(ctx, shot.track, shot.event)) notes.push(t(ctx, "Duration is locked while this shot has camera edits."));
      setText(refs.note, notes.join(" "));
    }
  }

  function renderInto(box, ctx) {
    const state = stateOf(ctx);
    watchToggle(ctx, box);
    const shot = ctx.project() ? playheadShot(ctx) : null;
    const key = signature(ctx, shot);
    if (!state.panel || state.panel.box !== box || state.panel.key !== key || !box.contains(state.panel.refs.root)) {
      // A rebuild (a new mode or shot) keeps keyboard focus on the same control. The new
      // fields are filled before the focus moves, since syncPanel leaves a focused field alone.
      const active = global.document && document.activeElement;
      const focused = active && box.contains(active) ? (active.dataset && active.dataset.mvCam ? `[data-mv-cam="${active.dataset.mvCam}"]` : active.id ? `#${active.id}` : null) : null;
      state.panel = { box, key, refs: build(ctx, box, shot) };
      syncPanel(ctx);
      if (focused) box.querySelector(focused)?.focus({ preventScroll: true });
      return;
    }
    syncPanel(ctx);
  }

  // timeChanged skips a closed panel, so the panel catches up with the playhead when it opens.
  function watchToggle(ctx, box) {
    const state = stateOf(ctx);
    const details = box && typeof box.closest === "function" ? box.closest("details") : null;
    if (!details || state.toggle === details) return;
    state.toggle = details;
    details.addEventListener("toggle", () => {
      if (details.open && !details.hidden && stateOf(ctx).toggle === details) renderPanel(ctx);
    });
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
    const ids = new Set(), records = new Set();
    const main = new Set(mainTracks(ctx.project()).map((track) => track.id));
    for (const change of command && Array.isArray(command.changes) ? command.changes : []) {
      const target = change.target || {}, path = change.path || [];
      if (target.kind === "editor" && path[0] === "camera") {
        if (path[1] === "shots" && typeof path[2] === "string") { ids.add(path[2]); records.add(path[2]); }
        else all = true;
      } else if (target.kind === "event" && main.has(target.track)) ids.add(target.event);
      else if (target.kind === "track" && main.has(target.track)) all = true;
    }
    if (all) return { events: undefined, records: [...records] };
    return ids.size ? { events: [...ids], records: [...records] } : null;
  }

  // The lanes whose key diamonds a record change moved. A bake redraws a lane only when the
  // samples change, and a key can move without changing them (a lone offset key).
  function refreshKeyLanes(ctx, records, skip) {
    if (!records.length) return;
    for (const track of mainTracks(ctx.project())) {
      if (!skip.has(track.id) && track.events.some((event) => event && records.includes(event.id))) ctx.refreshLane(track.id);
    }
  }

  // The shortcut a key press names. event.key wins when it is one of the Latin shortcut
  // characters; otherwise (Korean or Japanese input on, where K gives "ㅏ" or "Process", or
  // another non-Latin layout) the physical key in event.code decides.
  const SHORTCUT_CODES = { KeyK: "k", KeyI: "i", KeyD: "d", KeyA: "a", KeyC: "c", KeyV: "v", BracketLeft: "[", BracketRight: "]" };
  function shortcutKey(event) {
    const key = String(event.key || "").toLowerCase();
    if (/^[a-z[\]]$/.test(key) || key === "delete" || key === "backspace") return key;
    return SHORTCUT_CODES[event.code] || key;
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
        state.memory = new Map();
        state.differs = new WeakMap();
        state.panel = null;
        renderPanel(ctx);
        return;
      }
      // An asset import (reload) or a costume re-import can change what layers bake (members,
      // outfits); keys alone rebake to the same samples. Unedited shots are not visited.
      if (info.reason === "reload" || info.reason === "reimport") { state.panel = null; requestBake(ctx, { reason: info.reason }); }
      else if (info.reason === "history") {
        const focused = focusedKey(ctx);
        const scope = bakeScope(ctx, info.command);
        // Undo/redo: the keys selected with the records it brought back, before the lanes redraw.
        if (scope && info.direction && info.direction !== "do") restoreSelection(ctx, scope.records);
        if (scope) {
          state.refreshed = new Set();
          try { requestBake(ctx, { events: scope.events, reason: "history" }); } finally {
            refreshKeyLanes(ctx, scope.records, state.refreshed);
            state.refreshed = null;
          }
        } else renderPanel(ctx);
        if (focused && info.direction !== "do") refocusKey(ctx, focused);
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
      if (!durationLocked(ctx, track, event)) return undefined;
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
      const state = stateOf(ctx);
      const tab = typeof ctx.activeTab === "function" ? ctx.activeTab() : "";
      if (!panelOpen() && tab !== "camera" && tab !== "edit") return false;
      const key = shortcutKey(event);
      const command = event.ctrlKey || event.metaKey;
      const plain = command && !event.altKey && !event.shiftKey;
      if (plain && key === "d") { duplicateKey(ctx); return true; }
      // Copy/paste of keys, unless text on the page is selected (its copy stays the browser's).
      const text = global.getSelection ? String(global.getSelection() || "") : "";
      if (plain && key === "c") return !text && copyKeys(ctx);
      if (plain && key === "v" && state.clipboard) { pasteKeys(ctx); return true; }
      if (command || event.altKey) return false;
      if (key === "escape") return !event.shiftKey && clearSelection(ctx);
      switch (key) {
        case "k": keyView(ctx); return true;
        case "i": addKey(ctx); return true;
        case "delete": case "backspace": return deleteKeys(ctx) || !!targetKey(ctx);
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
    // Multi-key editing.
    ONE_SHOT, "Key selection", "Select all keys", "Clear selection", "Copy keys", "Paste keys", "No keys selected",
    "Keys selected: {count}", "Keys selected in shot {index}: {count}", "Time scale (%)", "Scale timing",
    "Scales the spacing of the selected keys around the first selected key (Alt+drag the last selected key on the timeline does the same).",
    "Add to selected keys", "Apply offset", SELECTION_HINT, "Move camera keys", "Delete camera keys", "Scale camera key timing",
    "Offset camera keys", "Paste camera keys", "Camera keys copied: {count}.", "Copy camera keys first.",
    "The copied keys do not fit in this shot.", "Keys outside this shot were left out: {count}.",
    "Select at least two keys to scale their timing.", "The timing stops at a neighbouring key or the end of the shot.",
    "Select several", MULTI_TITLE, TOUCH_HINT, "Delete selected keys",
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
      if (shot) { select(ctx, shot, frame); noteSelection(ctx); }
    },
    // Multi-key editing: the selection (one shot at a time) and the group commands.
    selectKeys: (ctx, eventId, frames, { add = false } = {}) => selectBoxed(ctx, new Map([[eventId, frames]]), add),
    toggleKey: (ctx, eventId, frame) => {
      const shot = findShot(ctx, eventId);
      if (shot) { toggleKey(ctx, shot, frame); selectionChanged(ctx); }
    },
    selectAllKeys, clearSelection, moveKeys, stretchKeys, scaleKeys, offsetKeys, deleteKeys, copyKeys, pasteKeys, moveBounds, planScale,
    selected: (ctx) => stateOf(ctx).selected && { ...stateOf(ctx).selected, frames: stateOf(ctx).selected.frames.slice() },
    pending: (ctx) => stateOf(ctx).pending || Promise.resolve(),
  });
})(typeof window !== "undefined" ? window : globalThis);
