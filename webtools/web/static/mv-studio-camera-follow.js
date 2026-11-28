/* MV Studio follow camera (MVStudioCameraFollow): a character-follow camera rig, like a
   Cinemachine follow camera, baked into the MainCamera shots it covers.

   A rig lives in project.editor.camera.rigs (editor data only; history stores it):

     { id: "rig-<8 hex>", type: "follow", label, start, end,          // absolute s, frame-snapped, >= 2 frames
       target: { slot, part },                                        // BodyPartType: 0 Head, 1 Head (all), 2 Face, 3 Hips, 4 Neck
       view: "front" | "back" | "left" | "right" | "custom", yaw,     // yaw (deg) is added to the preset
       frame: "stage" | "member", turnDamping,                        // member facing smoothing (s)
       angle: "fixed" | "pan" | "look",                               // what follows: position only / angle only / both
       distance, height, lateral,                                     // m, in the view frame; height above the look-at point
       aim: { height, side, forward },                                // look-at offset (m) in the reference frame
       fov, roll,                                                     // authored deg
       deadZone: { radius, height, hysteresis },                      // m, m (+-band), 0..0.95
       heightLock: { mode: "off" | "camera" | "aim" | "both", value: "start" | number },
       damping: { aimXZ, aimY, bodyXZ, bodyY },                       // time constants (s); 0 = none
       blendIn, blendOut }                                            // s; each at most half the rig length

   Evaluation is deterministic: a fixed 60 Hz grid from the rig start (the client's
   ResetTrace), the target path sampled from the scene (MVStudioScene.sampleMemberPath),
   then the client's stage-display-camera model: a dead zone with in/out hysteresis (XZ
   radius and Y band), separate XZ/Y damping of the look-at point and of the camera body,
   an optional height lock, and a look rotation. Nothing depends on playback history, so
   scrubbing and playing give the same pose.

   The rig is a layer of the camera editor (MVStudioCameraKeys.registerLayer, order 30):
   the bake blends it over the original or keyed motion of every shot it overlaps and
   writes the result into the shots' dense samples on their own grid. Those samples are
   what the native export writes and the game plays. This module never writes the shots
   or editor.camera.shots itself; it asks MVStudioCameraKeys.requestBake for a bake. */
(function (global) {
  "use strict";

  const M = global.MVStudioCameraMath;
  const FRAME_RATE = 60;
  const LANE = "camera-rigs", PANEL = "follow", LAYER = "follow-camera";
  const EPSILON = 1e-6, CACHE_SIZE = 8;
  const finite = Number.isFinite;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const clone = (value) => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  const snap = (seconds) => Math.round(seconds * FRAME_RATE) / FRAME_RATE;

  // ---- the rig record -------------------------------------------------------------------------
  const VIEWS = Object.freeze(["front", "back", "left", "right", "custom"]);
  // Front puts the camera on the audience side (+Z); right is the member's right (+X).
  const VIEW_YAW = Object.freeze({ front: 0, right: 90, back: 180, left: -90, custom: 0 });
  const FRAMES = Object.freeze(["stage", "member"]);
  // What follows the member:
  // - "fixed": position only. The camera keeps its direction (the view preset in the reference
  //   frame) and moves with the member.
  // - "pan": angle only. The camera stays where the rig starts and turns toward the member.
  // - "look": both. It moves with the member and turns toward the damped look-at point.
  // Rigs saved before the field existed keep "look".
  const ANGLES = Object.freeze(["fixed", "pan", "look"]);
  const LOCKS = Object.freeze(["off", "camera", "aim", "both"]);
  const PARTS = Object.freeze([0, 1, 2, 3, 4]);
  const DEFAULTS = Object.freeze({
    view: "front", yaw: 0, frame: "stage", angle: "fixed", turnDamping: .5, distance: 2.5, height: 0, lateral: 0,
    aim: Object.freeze({ height: 0, side: 0, forward: 0 }), fov: 30, roll: 0,
    deadZone: Object.freeze({ radius: .1, height: .1, hysteresis: .5 }),
    heightLock: Object.freeze({ mode: "off", value: "start" }),
    damping: Object.freeze({ aimXZ: .15, aimY: .3, bodyXZ: .35, bodyY: .5 }), blendIn: .5, blendOut: .5,
  });
  // Stored ranges of every number field (spec ranges; the sliders show a practical part).
  const LIMITS = Object.freeze({
    yaw: [-180, 180], turnDamping: [0, 5], distance: [.3, 30], height: [-5, 10], lateral: [-10, 10],
    "aim.height": [-5, 10], "aim.side": [-10, 10], "aim.forward": [-10, 10], fov: [1, 170], roll: [-180, 180],
    "deadZone.radius": [0, 2], "deadZone.height": [0, 2], "deadZone.hysteresis": [0, .95], "heightLock.value": [-10, 30],
    "damping.aimXZ": [0, 5], "damping.aimY": [0, 5], "damping.bodyXZ": [0, 5], "damping.bodyY": [0, 5],
    blendIn: [0, 600], blendOut: [0, 600],
  });

  function read(object, path) {
    let value = object;
    for (const key of path.split(".")) value = value && typeof value === "object" ? value[key] : undefined;
    return value;
  }

  function write(object, path, value) {
    const keys = path.split(".");
    let node = object;
    for (const key of keys.slice(0, -1)) node = node[key] && typeof node[key] === "object" ? node[key] : (node[key] = {});
    node[keys[keys.length - 1]] = value;
  }

  function number(raw, path) {
    const value = read(raw, path), [min, max] = LIMITS[path];
    return finite(value) ? clamp(value, min, max) : read(DEFAULTS, path);
  }

  // A stored rig checked and cleaned (always the same key order); null when it is not a rig.
  function normalizeRig(raw) {
    if (!raw || typeof raw !== "object" || typeof raw.id !== "string" || !raw.id || !finite(raw.start) || !finite(raw.end)) return null;
    const first = Math.max(0, Math.round(raw.start * FRAME_RATE));
    const last = Math.max(first + 2, Math.round(raw.end * FRAME_RATE));
    const target = raw.target && typeof raw.target === "object" ? raw.target : {};
    const lock = raw.heightLock && typeof raw.heightLock === "object" ? raw.heightLock : {};
    const value = lock.value === "start" || !finite(lock.value) ? "start" : clamp(lock.value, ...LIMITS["heightLock.value"]);
    return {
      id: raw.id, type: "follow", label: typeof raw.label === "string" ? raw.label.slice(0, 80) : "",
      start: first / FRAME_RATE, end: last / FRAME_RATE,
      target: { slot: Number.isInteger(target.slot) && target.slot >= 1 ? target.slot : 1, part: PARTS.includes(target.part) ? target.part : 0 },
      view: VIEWS.includes(raw.view) ? raw.view : DEFAULTS.view, yaw: number(raw, "yaw"),
      frame: FRAMES.includes(raw.frame) ? raw.frame : DEFAULTS.frame, turnDamping: number(raw, "turnDamping"),
      angle: ANGLES.includes(raw.angle) ? raw.angle : "look",
      distance: number(raw, "distance"), height: number(raw, "height"), lateral: number(raw, "lateral"),
      aim: { height: number(raw, "aim.height"), side: number(raw, "aim.side"), forward: number(raw, "aim.forward") },
      fov: number(raw, "fov"), roll: number(raw, "roll"),
      deadZone: { radius: number(raw, "deadZone.radius"), height: number(raw, "deadZone.height"), hysteresis: number(raw, "deadZone.hysteresis") },
      heightLock: { mode: LOCKS.includes(lock.mode) ? lock.mode : "off", value },
      damping: { aimXZ: number(raw, "damping.aimXZ"), aimY: number(raw, "damping.aimY"), bodyXZ: number(raw, "damping.bodyXZ"),
        bodyY: number(raw, "damping.bodyY") },
      blendIn: number(raw, "blendIn"), blendOut: number(raw, "blendOut"),
    };
  }

  function rigId() {
    const bytes = new Uint8Array(4);
    if (global.crypto && typeof global.crypto.getRandomValues === "function") global.crypto.getRandomValues(bytes);
    else for (let index = 0; index < 4; index++) bytes[index] = Math.floor(Math.random() * 256);
    return "rig-" + [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  }

  // The rig's 60 Hz grid: absolute frames first..last (t_n = (first + n) / 60).
  function frameRange(rig) {
    const first = Math.round(rig.start * FRAME_RATE), last = Math.round(rig.end * FRAME_RATE);
    return { first, last, count: last - first + 1 };
  }

  // Sorted-key JSON (cache keys).
  function stable(value) {
    if (value === undefined) return "null";
    if (value === null || typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) return "[" + value.map(stable).join(",") + "]";
    return "{" + Object.keys(value).filter((key) => value[key] !== undefined).sort()
      .map((key) => JSON.stringify(key) + ":" + stable(value[key])).join(",") + "}";
  }

  // ---- deterministic evaluation (spec 8.3) -------------------------------------------------------
  // Smoothing factor of one 1/60 s step for a time constant tau: after tau seconds a step input
  // leaves e^-1 of its error.
  const alpha = (tau) => tau > 0 ? 1 - Math.exp(-(1 / FRAME_RATE) / tau) : 1;
  const wrap = (degrees) => degrees - 360 * Math.round(degrees / 360);

  // Unity rotation about +Y by `degrees` ((0, 0, 1) -> (sin, 0, cos)).
  function turnY(degrees, x, y, z) {
    const radians = degrees * Math.PI / 180, sin = Math.sin(radians), cos = Math.cos(radians);
    return [x * cos + z * sin, y, z * cos - x * sin];
  }

  // The rig rotation (Unity [x, y, z, w]) that looks along its -Z from eye to target with +Y up,
  // rolled about its Z: three's Matrix4.lookAt (camera convention) and
  // Quaternion.setFromRotationMatrix in three space, mapped back with (x, -y, -z, w).
  function lookRotation(eye, target, roll) {
    let zx = target[0] - eye[0], zy = eye[1] - target[1], zz = eye[2] - target[2];   // three: eye - target, x mirrored
    if (zx * zx + zy * zy + zz * zz === 0) zz = 1;
    let length = Math.hypot(zx, zy, zz);
    zx /= length; zy /= length; zz /= length;
    // x = up × z with up = (0, 1, 0)
    let xx = zz, xy = 0, xz = -zx;
    if (xx * xx + xz * xz === 0) {
      zz += .0001;
      length = Math.hypot(zx, zy, zz);
      zx /= length; zy /= length; zz /= length;
      xx = zz; xz = -zx;
    }
    length = Math.hypot(xx, xy, xz);
    xx /= length; xz /= length;
    // y = z × x
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    const m11 = xx, m12 = yx, m13 = zx, m21 = xy, m22 = yy, m23 = zy, m31 = xz, m32 = yz, m33 = zz;
    const trace = m11 + m22 + m33;
    let x, y, z, w;
    if (trace > 0) {
      const s = .5 / Math.sqrt(trace + 1);
      w = .25 / s; x = (m32 - m23) * s; y = (m13 - m31) * s; z = (m21 - m12) * s;
    } else if (m11 > m22 && m11 > m33) {
      const s = 2 * Math.sqrt(1 + m11 - m22 - m33);
      w = (m32 - m23) / s; x = .25 * s; y = (m12 + m21) / s; z = (m13 + m31) / s;
    } else if (m22 > m33) {
      const s = 2 * Math.sqrt(1 + m22 - m11 - m33);
      w = (m13 - m31) / s; x = (m12 + m21) / s; y = .25 * s; z = (m23 + m32) / s;
    } else {
      const s = 2 * Math.sqrt(1 + m33 - m11 - m22);
      w = (m21 - m12) / s; x = (m13 + m31) / s; y = (m23 + m32) / s; z = .25 * s;
    }
    let rotation = [x, -y, -z, w];
    if (roll) rotation = M.multiply(rotation, M.eulerZXYToQuaternion({ roll }));
    // + 0 turns a -0 into 0, so a JSON round trip (save, reopen) keeps the samples equal.
    return M.normalize(rotation).map((value) => value + 0);
  }

  /* The rig's poses on its grid from the target path.
     path = { count, positions: Float64Array(3·count) (Unity), yaw: Float64Array(count) (deg) | null }
     → { count, first, positions, rotations (Unity quaternions), aims, fov } */
  function evaluateRig(rig, path) {
    const count = path.count, P = path.positions, Y = path.yaw;
    const positions = new Float64Array(3 * count), rotations = new Float64Array(4 * count), aims = new Float64Array(3 * count);
    const aimXZ = alpha(rig.damping.aimXZ), aimY = alpha(rig.damping.aimY);
    const bodyXZ = alpha(rig.damping.bodyXZ), bodyY = alpha(rig.damping.bodyY), turn = alpha(rig.turnDamping);
    const outerRadius = rig.deadZone.radius, outerBand = rig.deadZone.height, inner = 1 - rig.deadZone.hysteresis;
    const member = rig.frame === "member" && !!Y;
    const lock = rig.heightLock, lockAim = lock.mode === "aim" || lock.mode === "both", lockBody = lock.mode === "camera" || lock.mode === "both";
    const view = VIEW_YAW[rig.view] + rig.yaw, fixed = rig.angle === "fixed", pan = rig.angle === "pan";
    // Tracked point A (dead zone + look-at damping).
    let ax = P[0], ay = P[1], az = P[2], moving = false;
    const startAim = ay;
    // Reference yaw: the member's facing, unwrapped and smoothed (stage front: 0).
    let raw = member ? Y[0] : 0, unwrapped = raw, reference = raw;
    let bx = 0, by = 0, bz = 0, startBody = 0;
    for (let n = 0; n < count; n++) {
      if (n > 0) {
        const dx = P[3 * n] - ax, dy = P[3 * n + 1] - ay, dz = P[3 * n + 2] - az;
        const radius = moving ? outerRadius * inner : outerRadius, band = moving ? outerBand * inner : outerBand;
        moving = Math.hypot(dx, dz) > radius || Math.abs(dy) > band;
        if (moving) { ax += aimXZ * dx; az += aimXZ * dz; ay += aimY * dy; }
        if (member) {
          unwrapped += wrap(Y[n] - raw);
          raw = Y[n];
          reference += turn * (unwrapped - reference);
        }
      }
      const pointY = lockAim ? (lock.value === "start" ? startAim : lock.value) : ay;
      const offset = turnY(reference, rig.aim.side, rig.aim.height, rig.aim.forward);
      const aim = [ax + offset[0], pointY + offset[1], az + offset[2]];
      const goal = turnY(reference + view, rig.lateral, rig.height, rig.distance);
      const gx = aim[0] + goal[0], gy = aim[1] + goal[1], gz = aim[2] + goal[2];
      if (n === 0) { bx = gx; by = gy; bz = gz; startBody = by; }
      else if (!pan) { bx += bodyXZ * (gx - bx); bz += bodyXZ * (gz - bz); by += bodyY * (gy - by); }
      const eye = [bx, lockBody ? (lock.value === "start" ? startBody : lock.value) : by, bz];
      positions.set(eye, 3 * n);
      aims.set(aim, 3 * n);
      // Fixed angle: look along the view offset itself (eye - goal toward eye), so damping and the
      // dead zone move the camera without turning it.
      rotations.set(fixed ? lookRotation(goal, [0, 0, 0], rig.roll) : lookRotation(eye, aim, rig.roll), 4 * n);
    }
    return { count, first: frameRange(rig).first, positions, rotations, aims, fov: rig.fov };
  }

  // The pose at absolute time t: between grid samples floor(u) and ceil(u) (lerp, slerp, lerp).
  function poseAt(result, t) {
    let u = clamp(t * FRAME_RATE - result.first, 0, result.count - 1);
    let index = Math.floor(u), fraction = u - index;
    if (fraction < EPSILON) fraction = 0;
    else if (fraction > 1 - EPSILON) { index += 1; fraction = 0; }
    index = Math.min(index, result.count - 1);
    const position = Array.from(result.positions.subarray(3 * index, 3 * index + 3));
    const rotation = Array.from(result.rotations.subarray(4 * index, 4 * index + 4));
    if (!fraction || index + 1 >= result.count) return { position, rotation, fov: result.fov };
    const next = result.positions.subarray(3 * index + 3, 3 * index + 6);
    return {
      position: position.map((value, axis) => value + (next[axis] - value) * fraction),
      rotation: M.slerp(rotation, Array.from(result.rotations.subarray(4 * index + 4, 4 * index + 8)), fraction),
      fov: result.fov,
    };
  }

  const smooth = (x) => x * x * (3 - 2 * x);

  // Blend weight at absolute time t (0 outside the rig): smoothstep in and out, each at most half
  // the rig length; a zero blend is a cut.
  function weight(rig, t) {
    if (t < rig.start - EPSILON || t > rig.end + EPSILON) return 0;
    const half = (rig.end - rig.start) / 2;
    const blendIn = Math.min(rig.blendIn, half), blendOut = Math.min(rig.blendOut, half);
    const fadeIn = blendIn > 0 ? smooth(clamp((t - rig.start) / blendIn, 0, 1)) : 1;
    const fadeOut = blendOut > 0 ? smooth(clamp((rig.end - t) / blendOut, 0, 1)) : 1;
    return fadeIn * fadeOut;
  }

  // frame = mix(frame, pose, w) (the camera keys layer frame { t, position, rotation, fov }).
  function mix(frame, pose, w, fallbackFov) {
    if (w >= 1) {
      frame.position = pose.position.slice(0, 3);
      frame.rotation = pose.rotation.slice(0, 4);
      frame.fov = pose.fov;
      return;
    }
    frame.position = frame.position.map((value, axis) => value + (pose.position[axis] - value) * w);
    frame.rotation = M.slerp(M.normalize(frame.rotation), pose.rotation, w);
    const base = finite(frame.fov) ? frame.fov : finite(fallbackFov) ? fallbackFov : pose.fov;
    frame.fov = base + (pose.fov - base) * w;
  }

  // ---- per-editor state ---------------------------------------------------------------------------
  const states = new WeakMap();
  function stateOf(ctx) {
    let state = states.get(ctx);
    if (!state) {
      state = { cache: new Map(), evals: new Map(), inflight: new Map(), unavailable: new Map(), selected: null,
        dirty: false, cancelled: false, saving: false, retry: null, unlock: null, loads: 0, panel: null, toggle: null, lane: null,
        progressQueued: false, normalized: { source: null, rigs: [] } };
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

  const Keys = () => global.MVStudioCameraKeys || null;

  // The rigs of the open project, cleaned (cached per stored array).
  function rigsOf(ctx) {
    const editor = ctx.editor(false);
    const stored = editor && editor.camera && Array.isArray(editor.camera.rigs) ? editor.camera.rigs : null;
    const state = stateOf(ctx);
    if (state.normalized.source !== stored || state.normalized.text !== (stored ? JSON.stringify(stored) : "")) {
      state.normalized = { source: stored, text: stored ? JSON.stringify(stored) : "", rigs: stored ? stored.map(normalizeRig).filter(Boolean) : [] };
    }
    return state.normalized.rigs;
  }

  function findRig(ctx, id) { return rigsOf(ctx).find((rig) => rig.id === id) || null; }

  const shotRange = (shot) => [shot.event.start, shot.event.start + shot.event.duration];
  function overlaps(rig, start, end) { return start < rig.end - EPSILON && end > rig.start + EPSILON; }
  function overlapsShot(rig, shot) {
    const [start, end] = shotRange(shot);
    return overlaps(rig, start, end);
  }

  // ---- the target path: cache keys, scene sampling ------------------------------------------------
  const MEMBER_BINDING = /\/Members\/Member([1-9][0-9]*)(?:\/|$)/;
  function trackSlot(track) {
    const Tabs = global.MVStudioTimelineTabs;
    if (Tabs && typeof Tabs.memberSlot === "function") return Tabs.memberSlot(track);
    const match = MEMBER_BINDING.exec(String(track && track.binding || ""));
    return match ? Number(match[1]) : null;
  }

  /* What the member's path depends on (spec 8.5's cache key, without the time range: the cache
     holds samples per absolute frame, so a moved or longer rig reuses the frames it shares):
     slot and part, the performer (glb, transform, rig targets, costume), the timing of the
     events that drive its dance (its motion segments and the slot's dance tracks) and of its
     LiveMemberScalingTrack. No quality setting changes a member's pose in the preview. */
  function pathKey(ctx, rig) {
    const project = ctx.project() || {};
    const slot = rig.target.slot;
    const performer = (project.performers || []).find((item) => item && item.position === slot) || null;
    const segments = new Set(((performer && performer.motion && performer.motion.bodySegments) || [])
      .map((segment) => segment && segment.nativeEventId).filter(Boolean));
    const dance = [], scaling = [];
    for (const track of Array.isArray(project.tracks) ? project.tracks : []) {
      if (!track || !Array.isArray(track.events)) continue;
      const scaled = track.nativeClass === "LiveMemberScalingTrack" && new RegExp(`/Member${slot}/Model$`).test(track.binding || "");
      const own = track.kind === "dance" && trackSlot(track) === slot;
      for (const event of track.events) {
        if (!event) continue;
        if (own || segments.has(event.id)) dance.push([track.id, !!track.muted, event.id, event.start, event.duration, event.values || null]);
        if (scaled) scaling.push([track.id, !!track.muted, event.id, event.start, event.duration, event.values || null]);
      }
    }
    return stable({ slot, part: rig.target.part, project: project.name || "", source: project.source || null,
      performer: performer && { id: performer.id, glb: performer.glb || null, transform: performer.transform || null,
        focus: (performer.rig && performer.rig.focusParts) || null, costume: performer.costumeId ?? null },
      dance, scaling });
  }

  // LRU (8) of per-frame member samples: positions (Unity), facing yaw, and which frames are known.
  function cacheEntry(ctx, key, frames) {
    const state = stateOf(ctx);
    let entry = state.cache.get(key);
    if (entry) state.cache.delete(key);
    else entry = { key, positions: new Float64Array(0), yaw: new Float64Array(0), have: new Uint8Array(0), facing: null };
    state.cache.set(key, entry);
    while (state.cache.size > CACHE_SIZE) state.cache.delete(state.cache.keys().next().value);
    if (entry.have.length < frames) {
      const size = Math.max(frames, Math.ceil(entry.have.length * 1.5));
      const positions = new Float64Array(3 * size), yaw = new Float64Array(size), have = new Uint8Array(size);
      positions.set(entry.positions); yaw.set(entry.yaw); have.set(entry.have);
      Object.assign(entry, { positions, yaw, have });
    }
    return entry;
  }

  function slicePath(entry, rig, facing) {
    const { first, count } = frameRange(rig);
    return { count, positions: entry.positions.slice(3 * first, 3 * (first + count)),
      yaw: facing && entry.facing ? entry.yaw.slice(first, first + count) : null };
  }

  const abortError = () => new DOMException("The follow camera bake was cancelled.", "AbortError");

  function untilAborted(promise, signal) {
    if (!signal) return promise;
    if (signal.aborted) return Promise.reject(abortError());
    return new Promise((resolve, reject) => {
      const stop = () => reject(abortError());
      signal.addEventListener("abort", stop, { once: true });
      promise.then((value) => { signal.removeEventListener("abort", stop); resolve(value); },
        (error) => { signal.removeEventListener("abort", stop); reject(error); });
    });
  }

  // One frame (or 50 ms when frames do not run): rebakes from cached paths follow slider input
  // at most once per drawn frame.
  function nextFrame(signal) {
    const wait = new Promise((resolve) => {
      let timer = null, frame = 0;
      const done = () => { if (timer !== null) clearTimeout(timer); if (frame && global.cancelAnimationFrame) global.cancelAnimationFrame(frame); resolve(); };
      timer = setTimeout(done, typeof global.requestAnimationFrame === "function" ? 50 : 0);
      if (typeof global.requestAnimationFrame === "function") frame = global.requestAnimationFrame(done);
    });
    return untilAborted(wait, signal);
  }

  // Samples the frames of the rig the cache lacks (one sampling per path at a time; a running one
  // is shared). The sampling outlives a superseded bake and stops on Cancel or when no rig needs
  // its path. Returns true when it sampled.
  async function samplePath(ctx, scene, rig, key, entry, signal) {
    const state = stateOf(ctx);
    let sampled = false;
    for (;;) {
      const running = state.inflight.get(key);
      if (running) {
        sampled = true;
        await untilAborted(running.promise, signal);
        continue;
      }
      const { first, last } = frameRange(rig);
      const missing = [];
      for (let frame = first; frame <= last; frame++) if (!entry.have[frame]) missing.push(frame);
      if (!missing.length) return sampled;
      const controller = new AbortController();
      const task = { key, controller, total: missing.length, done: 0 };
      task.promise = (async () => {
        const result = await scene.sampleMemberPath({ slot: rig.target.slot, part: rig.target.part,
          times: Float64Array.from(missing, (frame) => frame / FRAME_RATE), signal: controller.signal,
          onProgress: (done) => { task.done = done; progressChanged(ctx); } });
        missing.forEach((frame, index) => {
          entry.positions.set(result.positions.subarray(3 * index, 3 * index + 3), 3 * frame);
          if (result.yaw) entry.yaw[frame] = result.yaw[index];
          entry.have[frame] = 1;
        });
        entry.facing = !!result.yaw;
      })();
      task.promise.catch(() => {}).finally(() => {
        if (state.inflight.get(key) === task) state.inflight.delete(key);
        progressChanged(ctx);
      });
      state.inflight.set(key, task);
      progressChanged(ctx);
      sampled = true;
      await untilAborted(task.promise, signal);
    }
  }

  // Stops samplings that no rig needs any more (a moved rig, another member).
  function dropObsolete(ctx, keys) {
    for (const [key, task] of stateOf(ctx).inflight) if (!keys.has(key)) task.controller.abort();
  }

  // Whether the rig's member can be sampled now: ok, wait (the 3D preview is still loading the
  // project), or a reason it cannot.
  function memberStatus(ctx, scene, rig) {
    const state = stateOf(ctx);
    if (!scene || typeof scene.memberTargets !== "function" || typeof scene.sampleMemberPath !== "function") {
      return { reason: "The 3D preview is not available, so the follow camera cannot be baked." };
    }
    const member = scene.memberTargets().find((item) => item.slot === rig.target.slot);
    if (!member) {
      // While an open/import runs (locked) the scene is still loading its members.
      if (ctx.locked() && !state.saving) return { wait: true };
      return { reason: "This member is not loaded in the 3D preview.", slot: rig.target.slot };
    }
    if (!member.parts.includes(rig.target.part)) return { reason: "This member has no target for the chosen body part.", member };
    return { ok: true, member };
  }

  // A bake skipped while the scene loads is requested again once the editor is unlocked.
  function scheduleRetry(ctx) {
    const state = stateOf(ctx);
    if (state.retry) return;
    const project = ctx.project();
    const tick = () => {
      state.retry = null;
      if (!project || ctx.project() !== project) return;
      if (ctx.locked()) { state.retry = setTimeout(tick, 200); return; }
      requestBake(ctx, "retry");
    };
    state.retry = setTimeout(tick, 200);
  }

  // The host re-renders only its own panels when an open or import releases the editor. A panel
  // built while it was locked (projectChanged "load" runs before the unlock) has its controls
  // disabled, so it is rendered again once the editor is unlocked. Another load stops the wait.
  function renderWhenUnlocked(ctx) {
    const state = stateOf(ctx);
    if (state.unlock || !ctx.locked()) return;
    const loads = state.loads;
    const tick = () => {
      state.unlock = null;
      if (state.loads !== loads) return;
      if (ctx.locked()) { state.unlock = setTimeout(tick, 100); return; }
      renderPanel(ctx);
    };
    state.unlock = setTimeout(tick, 100);
  }

  // Layer prepare (awaited by MVStudioCameraKeys.requestBake; a newer request aborts `signal`).
  async function prepare(ctx, shots, signal) {
    const state = stateOf(ctx);
    const all = rigsOf(ctx);
    const rigs = all.filter((rig) => shots.some((shot) => overlapsShot(rig, shot)));
    if (!rigs.length) return;
    state.dirty = true;
    state.cancelled = false;
    dropObsolete(ctx, new Set(all.map((rig) => pathKey(ctx, rig))));
    const scene = ctx.scene();
    const statuses = rigs.map((rig) => memberStatus(ctx, scene, rig));
    if (statuses.some((status) => status.wait)) {
      scheduleRetry(ctx);
      renderPanel(ctx);
      throw abortError();
    }
    let sampled = false;
    for (const [index, rig] of rigs.entries()) {
      const status = statuses[index];
      if (!status.ok) {
        state.unavailable.set(rig.id, status);
        state.evals.delete(rig.id);
        continue;
      }
      const key = pathKey(ctx, rig);
      const entry = cacheEntry(ctx, key, frameRange(rig).last + 1);
      try {
        if (await samplePath(ctx, scene, rig, key, entry, signal)) sampled = true;
      } catch (error) {
        if (signal.aborted || (error && error.name === "AbortError")) throw abortError();
        console.error(error);
        state.unavailable.set(rig.id, { reason: "This member is not loaded in the 3D preview.", slot: rig.target.slot });
        state.evals.delete(rig.id);
        continue;
      }
      state.unavailable.delete(rig.id);
      const path = slicePath(entry, rig, status.member.facing);
      state.evals.set(rig.id, { rig: stable(rig), result: evaluateRig(rig, path), facing: !!path.yaw });
    }
    if (!sampled) await nextFrame(signal);
    if (signal.aborted) throw abortError();
    state.dirty = false;
    renderPanel(ctx);
  }

  // Layer apply: every rig over the shot, in array order (later rigs blend over earlier ones).
  function apply(ctx, shot, frames) {
    const state = stateOf(ctx);
    for (const rig of rigsOf(ctx)) {
      if (!overlapsShot(rig, shot)) continue;
      const evaluated = state.evals.get(rig.id);
      if (!evaluated || evaluated.rig !== stable(rig)) continue;
      for (const frame of frames) {
        const w = weight(rig, frame.t);
        if (w > 0) mix(frame, poseAt(evaluated.result, frame.t), w, shot.fallbackFov);
      }
    }
  }

  const layer = Object.freeze({
    id: LAYER, order: 30,
    // A shot the native writer accepts (camera keys' editable rule) under a rig.
    affects: (ctx, shot) => !!shot && !!shot.editable && !!shot.source && rigsOf(ctx).some((rig) => overlapsShot(rig, shot)),
    prepare: (ctx, shots, signal) => prepare(ctx, shots, signal),
    apply: (ctx, shot, frames) => apply(ctx, shot, frames),
  });

  function requestBake(ctx, reason = "follow") {
    const keys = Keys();
    if (!keys || !ctx.project()) return Promise.resolve();
    return keys.requestBake(ctx, { reason });
  }

  // Cancel: stops every member sampling; the shots keep the samples they had.
  function cancel(ctx) {
    const state = stateOf(ctx);
    state.cancelled = true;
    for (const task of state.inflight.values()) task.controller.abort();
    renderPanel(ctx);
  }

  // ---- commands -----------------------------------------------------------------------------------
  function cleanList(rigs) { return rigs.map(normalizeRig).filter(Boolean); }

  function commitRigs(ctx, rigs, label, detail = "", coalesce) {
    if (ctx.locked() || !ctx.history) return false;
    const editor = ctx.editor(false);
    const changes = [];
    if (!editor || !editor.camera || editor.camera.version !== 1) changes.push({ target: { kind: "editor" }, path: ["camera", "version"], after: 1 });
    const list = cleanList(rigs);
    changes.push({ target: { kind: "editor" }, path: ["camera", "rigs"], after: list.length ? list : undefined });
    const command = { label, detail, changes };
    if (coalesce) command.coalesce = coalesce;
    return ctx.history.apply(command);
  }

  function lowestSlot(ctx) {
    const scene = ctx.scene();
    const loaded = scene && typeof scene.memberTargets === "function" ? scene.memberTargets().map((item) => item.slot) : [];
    const listed = ((ctx.project() || {}).performers || []).map((item) => item && item.position).filter(Number.isInteger);
    const slots = (loaded.length ? loaded : listed).slice().sort((a, b) => a - b);
    return slots.length ? slots[0] : null;
  }

  // "Add follow camera": at the playhead, covering the shot there (spec defaults). A non-native
  // project with no camera shot there first gets one (MVStudioCameraKeys.ensureUserShot), in the
  // same undo step.
  function addRig(ctx, overrides = {}) {
    const keys = Keys(), project = ctx.project();
    if (!keys || !project || ctx.locked()) return null;
    const slot = Number.isInteger(overrides.slot) ? overrides.slot : lowestSlot(ctx);
    if (slot === null) { ctx.report(t(ctx, "No members to follow. Add a performer first."), true); return null; }
    const duration = Math.max(0, project.duration);
    const time = clamp(ctx.time(), 0, duration);
    let shot = keys.playheadShot(ctx, time);
    let start, end;
    const token = ctx.history.begin("Add follow camera");
    try {
      if (!shot && project.nativeTimeline !== true) {
        const created = keys.ensureUserShot(ctx, time, time + 4);
        if (created) shot = keys.shotInfo(ctx, created.track, created.event, time);
      }
      if (shot) { start = shot.event.start; end = shot.event.start + shot.event.duration; }
      else { start = time; end = time + 4; }
      start = clamp(snap(start), 0, Math.max(0, duration - 2 / FRAME_RATE));
      end = clamp(snap(end), start + 2 / FRAME_RATE, Math.max(start + 2 / FRAME_RATE, duration));
      const rigs = rigsOf(ctx).slice();
      const labels = new Set(rigs.map((item) => item.label));
      let index = rigs.length + 1;
      while (labels.has(format(ctx, "Follow camera {index}", { index }))) index++;
      const rig = normalizeRig({ ...clone(DEFAULTS), id: rigId(), type: "follow",
        label: format(ctx, "Follow camera {index}", { index }), start, end, target: { slot, part: 0 }, ...overrides });
      rigs.push(rig);
      stateOf(ctx).selected = rig.id;
      if (!commitRigs(ctx, rigs, "Add follow camera", rig.label)) return null;
      return rig;
    } finally {
      ctx.history.end(token);
      renderPanel(ctx);
    }
  }

  function updateRig(ctx, id, change, label, detail, coalesce) {
    const rigs = rigsOf(ctx).map((rig) => {
      if (rig.id !== id) return rig;
      const next = clone(rig);
      change(next);
      return next;
    });
    return commitRigs(ctx, rigs, label, detail, coalesce);
  }

  function setField(ctx, id, path, value, coalesce) {
    if (!LIMITS[path] && !["view", "frame", "angle", "label", "target.slot", "target.part", "heightLock.mode", "heightLock.value"].includes(path)) return false;
    return updateRig(ctx, id, (rig) => write(rig, path, value), "Edit follow camera", path, coalesce);
  }

  // A view preset. Switching to Custom keeps the current direction (preset + offset becomes the
  // offset); a preset from Custom starts at its own direction.
  function setView(ctx, id, view) {
    const rig = findRig(ctx, id);
    if (!rig || !VIEWS.includes(view) || rig.view === view) return false;
    const yaw = view === "custom" ? wrap(VIEW_YAW[rig.view] + rig.yaw) : rig.view === "custom" ? 0 : rig.yaw;
    return updateRig(ctx, id, (next) => { next.view = view; next.yaw = yaw; }, "Edit follow camera", "view");
  }

  const FRAMINGS = Object.freeze({
    close: { distance: 1.3, fov: 24, aim: { height: 0 } },
    medium: { distance: 2.5, fov: 30, aim: { height: -.2 } },
    full: { distance: 5.5, fov: 30, aim: { height: -.7 } },
  });

  function setFraming(ctx, id, framing) {
    const preset = FRAMINGS[framing];
    if (!preset) return false;
    return updateRig(ctx, id, (rig) => { rig.distance = preset.distance; rig.fov = preset.fov; rig.aim.height = preset.aim.height; },
      "Edit follow camera", framing);
  }

  function setRange(ctx, id, start, end, label = "Move follow camera") {
    const project = ctx.project();
    const duration = project ? Math.max(0, project.duration) : 0;
    const first = clamp(snap(start), 0, Math.max(0, duration - 2 / FRAME_RATE));
    const last = clamp(snap(end), first + 2 / FRAME_RATE, Math.max(first + 2 / FRAME_RATE, duration));
    return updateRig(ctx, id, (rig) => { rig.start = first; rig.end = last; }, label);
  }

  function deleteRig(ctx, id) {
    const rigs = rigsOf(ctx);
    const index = rigs.findIndex((rig) => rig.id === id);
    if (index < 0) return false;
    const state = stateOf(ctx);
    const next = rigs.filter((rig) => rig.id !== id);
    if (state.selected === id) state.selected = next.length ? next[Math.min(index, next.length - 1)].id : null;
    const changed = commitRigs(ctx, next, "Delete follow camera", rigs[index].label);
    renderPanel(ctx);
    return changed;
  }

  // A copy right after the original (same length), or over it when the MV ends there.
  function duplicateRig(ctx, id) {
    const rigs = rigsOf(ctx), project = ctx.project();
    const source = rigs.find((rig) => rig.id === id);
    if (!source || !project) return null;
    const length = source.end - source.start, duration = Math.max(0, project.duration);
    const copy = { ...clone(source), id: rigId(), label: format(ctx, "{label} copy", { label: source.label || t(ctx, "Follow camera") }) };
    if (source.end + 2 / FRAME_RATE <= duration) { copy.start = source.end; copy.end = Math.min(duration, source.end + length); }
    const next = rigs.slice();
    next.splice(rigs.indexOf(source) + 1, 0, copy);
    stateOf(ctx).selected = copy.id;
    const changed = commitRigs(ctx, next, "Duplicate follow camera", source.label);
    renderPanel(ctx);
    return changed ? normalizeRig(copy) : null;
  }

  function selectRig(ctx, id, { open = true, seek = true } = {}) {
    const rig = findRig(ctx, id);
    if (!rig) return false;
    stateOf(ctx).selected = id;
    if (seek && (ctx.time() < rig.start || ctx.time() > rig.end)) ctx.seek(rig.start, { audio: false });
    if (open) openPanel();
    drawLane(ctx);
    renderPanel(ctx);
    return true;
  }

  function selectedRig(ctx) {
    const state = stateOf(ctx), rigs = rigsOf(ctx);
    let rig = rigs.find((item) => item.id === state.selected) || null;
    if (!rig && rigs.length) {
      const time = ctx.time();
      rig = rigs.find((item) => item.start <= time && time <= item.end) || rigs[0];
      state.selected = rig.id;
    }
    return rig;
  }

  // ---- timeline lane ------------------------------------------------------------------------------
  function mainTrackId(ctx) {
    const keys = Keys();
    const shots = keys ? keys.mainCameraShots(ctx) : [];
    return shots.length ? shots[0].track.id : null;
  }

  function laneTitle(ctx, rig) {
    return format(ctx, "{label} · {start}–{end} · Member {slot}", { label: rig.label || t(ctx, "Follow camera"),
      start: formatTime(rig.start), end: formatTime(rig.end), slot: rig.target.slot });
  }

  function drawLane(ctx, lane = null, layout = null) {
    const state = stateOf(ctx);
    if (lane) state.lane = { element: lane, layout };
    const current = state.lane;
    if (!current || !current.element || !current.element.isConnected && !lane) return;
    const element = current.element, pps = current.layout && finite(current.layout.pixelsPerSecond) ? current.layout.pixelsPerSecond : 1;
    // A redraw (an undo, a nudge) keeps the keyboard focus on the same rig.
    const active = global.document ? document.activeElement : null;
    const focused = active && element.contains(active) && active.classList.contains("mv-rig-clip") ? active.dataset.rig : null;
    for (const node of [...element.querySelectorAll(".mv-rig-clip")]) { node.mvDetach?.(); node.remove(); }
    const rigs = rigsOf(ctx), rows = [], selected = selectedRig(ctx);
    for (const rig of rigs.slice().sort((a, b) => a.start - b.start)) {
      const left = rig.start * pps, width = Math.max(13, (rig.end - rig.start) * pps);
      const free = rows.findIndex((end) => end + 1 < left), row = free < 0 ? rows.length : free;
      rows[row] = left + width;
      const clip = ctx.make("button", null, { type: "button", class: "mv-rig-clip", "data-rig": rig.id, "data-track": LANE,
        title: laneTitle(ctx, rig), "aria-pressed": String(!!selected && selected.id === rig.id), "aria-describedby": "mv-clip-help" });
      const name = ctx.make("span", rig.label || t(ctx, "Follow camera"), { class: "mv-rig-name" });
      clip.append(name);
      const half = (rig.end - rig.start) / 2;
      for (const [side, seconds] of [["in", Math.min(rig.blendIn, half)], ["out", Math.min(rig.blendOut, half)]]) {
        if (seconds <= 0) continue;
        const ramp = ctx.make("span", null, { class: `mv-rig-blend mv-rig-blend-${side}`, "aria-hidden": "true" });
        ramp.style.width = `${Math.min(width, seconds * pps)}px`;
        clip.append(ramp);
      }
      clip.style.left = `${left}px`;
      clip.style.width = `${width}px`;
      clip.style.setProperty("--mv-clip-row", row);
      if (state.unavailable.has(rig.id)) clip.classList.add("mv-rig-unavailable");
      attachClip(ctx, clip, rig.id);
      element.append(clip);
    }
    element.style.setProperty("--mv-lane-rows", Math.max(rows.length, 1));
    if (focused) focusClip(focused);
  }

  // The host redraws the timeline for structural edits only: the rig lane comes and goes with
  // the first and the last rig.
  const LANE_TABS = Object.freeze(["camera", "edit", "all"]);
  function laneWanted(ctx) { return rigsOf(ctx).length > 0 && panelAvailable(ctx); }
  function syncLanePresence(ctx) {
    if (!global.document || typeof ctx.activeTab !== "function" || !LANE_TABS.includes(ctx.activeTab()) || !ctx.project()) return;
    if (stateOf(ctx).laneListed !== laneWanted(ctx)) ctx.renderTimeline();
  }

  function attachClip(ctx, clip, id) {
    clip.addEventListener("click", (event) => {
      event.stopPropagation();
      selectRig(ctx, id);
      focusClip(id);
    });
    clip.addEventListener("keydown", (event) => {
      if ((event.key === "Delete" || event.key === "Backspace") && !event.altKey && !event.ctrlKey && !event.metaKey && !ctx.locked()) {
        event.preventDefault();
        event.stopPropagation();
        deleteRig(ctx, id);
      }
    });
    if (typeof ctx.attachDrag !== "function") return;
    const place = (range) => {
      const pps = stateOf(ctx).lane?.layout?.pixelsPerSecond || 1;
      clip.style.left = `${range.start * pps}px`;
      clip.style.width = `${Math.max(13, (range.end - range.start) * pps)}px`;
    };
    clip.mvDetach = ctx.attachDrag(clip, {
      label: "Move follow camera",
      edges: { start: true, end: true },
      getRange: () => { const rig = findRig(ctx, id); return rig ? { start: rig.start, end: rig.end } : null; },
      bounds: () => ({ min: 0, max: ctx.duration(), minLength: 2 / FRAME_RATE }),
      snapTargets: () => {
        const targets = typeof ctx.snapTargets === "function" ? ctx.snapTargets() : [ctx.time()];
        for (const rig of rigsOf(ctx)) if (rig.id !== id) targets.push(rig.start, rig.end);
        return targets;
      },
      allowed: () => ctx.locked() ? { move: false, resize: false } : {},
      setRange: (range, { phase, mode }) => {
        const rig = findRig(ctx, id);
        if (!rig) return;
        if (phase === "preview") {
          place(range);
          clip.dataset.dragTime = formatTime(mode === "end" ? range.end : range.start);
          return;
        }
        delete clip.dataset.dragTime;
        if (phase === "cancel") { place(rig); return; }
        const hadFocus = global.document && clip === document.activeElement;
        const label = mode === "move" ? "Move follow camera" : "Resize follow camera";
        stateOf(ctx).selected = id;
        if (!setRange(ctx, id, range.start, range.end, label)) place(rig);
        if (hadFocus) focusClip(id);
      },
    });
  }

  function focusClip(id) {
    if (!global.document || typeof CSS === "undefined") return;
    document.querySelector(`.mv-rig-clip[data-rig="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
  }

  // ---- the Follow camera panel ----------------------------------------------------------------------
  const PART_LABELS = Object.freeze({ 0: "Head", 1: "Head (whole)", 2: "Face", 3: "Hips", 4: "Neck" });
  const VIEW_LABELS = Object.freeze({ front: "Front view", back: "Back view", left: "Left view", right: "Right view", custom: "Custom view" });
  const FRAMING_LABELS = Object.freeze({ close: "Close-up", medium: "Medium shot", full: "Full shot" });
  const LOCK_LABELS = Object.freeze({ off: "Off", camera: "Camera", aim: "Look-at point", both: "Both" });
  // [path, label, slider min, max, step]
  const FIELDS = Object.freeze({
    yaw: ["yaw", "Yaw offset (°)", -180, 180, 1], turnDamping: ["turnDamping", "Turn damping (s)", 0, 3, .05],
    distance: ["distance", "Distance (m)", .3, 15, .05], height: ["height", "Height (m)", -3, 5, .05],
    lateral: ["lateral", "Side offset (m)", -5, 5, .05],
    aimHeight: ["aim.height", "Look-at height (m)", -2, 2, .01], aimSide: ["aim.side", "Look-at side (m)", -3, 3, .01],
    aimForward: ["aim.forward", "Look-at forward (m)", -3, 3, .01],
    fov: ["fov", "FOV (°)", 5, 90, .5], roll: ["roll", "Roll (°)", -45, 45, .5],
    radius: ["deadZone.radius", "Radius (m)", 0, 1, .01], band: ["deadZone.height", "Height band (m)", 0, 1, .01],
    hysteresis: ["deadZone.hysteresis", "Hysteresis", 0, .95, .05],
    lockValue: ["heightLock.value", "Fixed height (m)", -2, 6, .01],
    aimXZ: ["damping.aimXZ", "Look-at XZ (s)", 0, 2, .01], aimY: ["damping.aimY", "Look-at Y (s)", 0, 2, .01],
    bodyXZ: ["damping.bodyXZ", "Camera XZ (s)", 0, 2, .01], bodyY: ["damping.bodyY", "Camera Y (s)", 0, 2, .01],
    blendIn: ["blendIn", "Blend in (s)", 0, 5, .05], blendOut: ["blendOut", "Blend out (s)", 0, 5, .05],
  });

  function panelAvailable(ctx) {
    const project = ctx.project(), keys = Keys();
    if (!project || !keys) return false;
    if (project.nativeTimeline !== true) return true;
    return keys.mainCameraShots(ctx).some(({ track, event }) => keys.shotInfo(ctx, track, event)?.editable);
  }

  function panelNode() { return global.document ? document.getElementById("mv-panel-" + PANEL) : null; }

  function openPanel() {
    const panel = panelNode();
    if (!panel || panel.hidden) return false;
    panel.open = true;
    panel.scrollIntoView?.({ block: "nearest" });
    return true;
  }

  function renderPanel(ctx) {
    if (!global.document || typeof ctx.renderPanel !== "function") return;
    ctx.renderPanel(PANEL);
  }

  // Progress redraws are batched to one per frame.
  function progressChanged(ctx) {
    const state = stateOf(ctx);
    if (state.progressQueued || !global.document) return;
    state.progressQueued = true;
    const run = () => { state.progressQueued = false; syncStatus(ctx); };
    if (typeof global.requestAnimationFrame === "function") global.requestAnimationFrame(run); else setTimeout(run, 0);
  }

  function progress(ctx) {
    let done = 0, total = 0;
    for (const task of stateOf(ctx).inflight.values()) { done += task.done; total += task.total; }
    return total ? { done, total, percent: Math.floor(100 * done / total) } : null;
  }

  function members(ctx) {
    const scene = ctx.scene();
    const loaded = scene && typeof scene.memberTargets === "function" ? scene.memberTargets() : [];
    const performers = (ctx.project() || {}).performers || [];
    const slots = new Map();
    for (const performer of performers) {
      if (!performer || !Number.isInteger(performer.position) || slots.has(performer.position)) continue;
      // The timeline's member chips name a performer the same way (MVStudioTimelineTabs.memberChoices).
      const name = String(performer.label || performer.memberName || "").trim();
      slots.set(performer.position, { slot: performer.position, parts: null, facing: false,
        name: name && !/^Member \d+$/.test(name) && name !== String(performer.memberId ?? "") ? name : "" });
    }
    for (const item of loaded) slots.set(item.slot, { ...(slots.get(item.slot) || { slot: item.slot, name: "" }), parts: item.parts, facing: item.facing });
    return [...slots.values()].sort((a, b) => a.slot - b.slot);
  }

  function signature(ctx, rig, list) {
    const language = [global.document && document.documentElement ? document.documentElement.lang : "", t(ctx, "Follow camera")].join("/");
    if (!rig) return ["none", ctx.locked(), language, list.map((item) => item.slot).join(",")].join("|");
    return [rig.id, rigsOf(ctx).map((item) => item.id + ":" + item.label).join(","), ctx.locked(), language, rig.view, rig.frame, rig.angle,
      rig.heightLock.mode, rig.heightLock.value === "start", list.map((item) => `${item.slot}:${item.name}:${(item.parts || []).join(".")}`).join(",")].join("|");
  }

  function section(ctx, root, legend, note) {
    const box = ctx.make("fieldset", null, { class: "mv-follow-section" });
    box.append(ctx.make("legend", t(ctx, legend)));
    if (note) box.append(ctx.make("p", t(ctx, note), { class: "mv-field-note mv-follow-help" }));
    const grid = ctx.make("div", null, { class: "mv-form-grid" });
    box.append(grid);
    root.append(box);
    return grid;
  }

  // A number with a slider: a slider drag is one undo step (a history gesture); keyboard steps on
  // the slider coalesce; the number field writes on change.
  function slider(ctx, refs, grid, rig, name, { disabled = false, title = "" } = {}) {
    const [path, label, min, max, step] = FIELDS[name];
    const [lowest, highest] = LIMITS[path];
    const row = ctx.make("label", null, { "data-mv-follow-row": path });
    const text = ctx.make("span", t(ctx, label));
    if (title) text.title = t(ctx, title);
    const box = ctx.make("span", null, { class: "mv-follow-slider" });
    const range = ctx.make("input", null, { type: "range", min: String(min), max: String(max), step: String(step),
      "data-mv-follow-range": path, "aria-label": t(ctx, label), tabindex: "-1" });
    const input = ctx.make("input", null, { type: "number", min: String(lowest), max: String(highest), step: String(step),
      "data-mv-follow": path, "aria-label": t(ctx, label) });
    if (title) input.title = range.title = t(ctx, title);
    range.disabled = input.disabled = disabled || ctx.locked();
    let token = null;
    const finish = () => { if (token) ctx.history.end(token); token = null; };
    range.addEventListener("pointerdown", () => {
      if (!range.disabled && !token) token = ctx.history.begin("Edit follow camera", { owner: range });
    });
    range.addEventListener("input", () => {
      const value = Number(range.value);
      if (!finite(value)) return;
      input.value = String(value);
      setField(ctx, rig.id, path, value, token ? undefined : `follow:${rig.id}:${path}`);
    });
    range.addEventListener("change", finish);
    range.addEventListener("pointerup", finish);
    range.addEventListener("pointercancel", finish);
    input.addEventListener("change", () => {
      if (input.value === "" || !finite(input.valueAsNumber)) { syncPanel(ctx); return; }
      setField(ctx, rig.id, path, clamp(input.valueAsNumber, lowest, highest));
      syncPanel(ctx, input);
    });
    box.append(range, input);
    row.append(text, box);
    grid.append(row);
    refs.fields[path] = { range, input };
    return row;
  }

  function select(ctx, attrs, options, value, onChange) {
    const control = ctx.make("select", null, attrs);
    for (const [id, label, disabled] of options) {
      const option = new Option(label, String(id));
      if (disabled) option.disabled = true;
      control.append(option);
    }
    control.value = String(value);
    control.disabled = ctx.locked();
    control.addEventListener("change", () => onChange(control.value));
    return control;
  }

  function labelled(ctx, grid, label, control) {
    const row = ctx.make("label");
    row.append(ctx.make("span", t(ctx, label)), control);
    grid.append(row);
    return row;
  }

  function build(ctx, box) {
    const state = stateOf(ctx);
    const refs = { fields: {}, root: ctx.make("div", null, { class: "mv-follow" }) };
    const root = refs.root;
    box.replaceChildren(root);
    const locked = ctx.locked();
    const rigs = rigsOf(ctx), rig = selectedRig(ctx), list = members(ctx);
    refs.key = signature(ctx, rig, list);

    const top = ctx.make("div", null, { class: "mv-follow-top" });
    refs.add = ctx.button(t(ctx, "Add follow camera"), () => { const added = addRig(ctx); if (added) { drawLane(ctx); focusClip(added.id); } },
      { id: "mv-follow-add", class: "mv-follow-primary", title: t(ctx, "Makes a camera that follows a member, like a Cinemachine follow camera. It covers the shot at the playhead.") });
    refs.add.disabled = locked || !list.length;
    top.append(refs.add);
    root.append(top);
    if (!rig) {
      root.append(ctx.make("p", t(ctx, list.length ? "Makes a camera that follows a member, like a Cinemachine follow camera. It covers the shot at the playhead."
        : "No members to follow. Add a performer first."), { class: "mv-field-note", id: "mv-follow-empty" }));
      refs.status = ctx.make("div", null, { class: "mv-follow-status", id: "mv-follow-status", "aria-live": "polite" });
      root.append(refs.status);
      return refs;
    }

    // Rig choice, name, duplicate, delete.
    const head = ctx.make("div", null, { class: "mv-form-grid mv-follow-head" });
    if (rigs.length > 1) {
      const choice = select(ctx, { id: "mv-follow-rig" }, rigs.map((item) => [item.id, `${item.label || t(ctx, "Follow camera")} · ${formatTime(item.start)}–${formatTime(item.end)}`]),
        rig.id, (value) => selectRig(ctx, value, { open: false }));
      labelled(ctx, head, "Rig", choice);
    }
    const name = ctx.make("input", null, { type: "text", id: "mv-follow-name", maxlength: "80", "aria-label": t(ctx, "Rig name") });
    name.value = rig.label;
    name.disabled = locked;
    name.addEventListener("change", () => setField(ctx, rig.id, "label", name.value.trim()));
    labelled(ctx, head, "Rig name", name);
    const range = ctx.make("span", null, { class: "mv-inline-fields mv-follow-range" });
    for (const [key, label] of [["start", "Start (s)"], ["end", "End (s)"]]) {
      const input = ctx.make("input", null, { type: "number", step: String(1 / FRAME_RATE), min: "0", max: String(ctx.duration()),
        "data-mv-follow": key, "aria-label": t(ctx, label), title: t(ctx, label), placeholder: t(ctx, label) });
      input.disabled = locked;
      input.addEventListener("change", () => {
        const current = findRig(ctx, rig.id);
        if (!current || !finite(input.valueAsNumber)) { syncPanel(ctx); return; }
        setRange(ctx, rig.id, key === "start" ? input.valueAsNumber : current.start, key === "end" ? input.valueAsNumber : current.end,
          key === "start" ? "Move follow camera" : "Resize follow camera");
        syncPanel(ctx, input);
      });
      refs.fields[key] = { input };
      const cell = ctx.make("span", null, { class: "mv-follow-range-field" });
      cell.append(ctx.make("span", t(ctx, label), { class: "mv-follow-caption", "aria-hidden": "true" }), input);
      range.append(cell);
    }
    const timing = ctx.make("div", null, { class: "mv-follow-row" });
    timing.append(ctx.make("span", t(ctx, "Time range")), range);
    head.append(timing);
    root.append(head);
    const tools = ctx.make("div", null, { class: "mv-follow-tools" });
    refs.duplicate = ctx.button(t(ctx, "Duplicate rig"), () => { const copy = duplicateRig(ctx, rig.id); if (copy) drawLane(ctx); }, { id: "mv-follow-duplicate" });
    refs.remove = ctx.button(t(ctx, "Delete rig"), () => { deleteRig(ctx, rig.id); drawLane(ctx); }, { id: "mv-follow-delete" });
    refs.duplicate.disabled = refs.remove.disabled = locked;
    tools.append(refs.duplicate, refs.remove);
    root.append(tools);

    // Target.
    const target = section(ctx, root, "Target");
    const memberOptions = list.map((item) => [item.slot, item.name ? `${item.slot} · ${item.name}` : `${t(ctx, "Member")} ${item.slot}`, item.parts === null]);
    if (!list.some((item) => item.slot === rig.target.slot)) memberOptions.push([rig.target.slot, `${t(ctx, "Member")} ${rig.target.slot}`, true]);
    labelled(ctx, target, "Member", select(ctx, { id: "mv-follow-member" }, memberOptions, rig.target.slot,
      (value) => setField(ctx, rig.id, "target.slot", Number(value))));
    const parts = (list.find((item) => item.slot === rig.target.slot) || {}).parts;
    labelled(ctx, target, "Body part", select(ctx, { id: "mv-follow-part" },
      PARTS.map((part) => [part, t(ctx, PART_LABELS[part]), Array.isArray(parts) && !parts.includes(part)]), rig.target.part,
      (value) => setField(ctx, rig.id, "target.part", Number(value))));

    // View.
    const view = section(ctx, root, "Camera view", "Front puts the camera on the audience side; Right is the member's right.");
    const presets = ctx.make("div", null, { class: "mv-follow-presets", role: "group", "aria-label": t(ctx, "Camera view") });
    for (const id of VIEWS) {
      const control = ctx.button(t(ctx, VIEW_LABELS[id]), () => setView(ctx, rig.id, id), { "data-mv-follow-view": id, "aria-pressed": String(rig.view === id) });
      control.disabled = locked;
      presets.append(control);
    }
    view.parentNode.insertBefore(presets, view);
    slider(ctx, refs, view, rig, "yaw", { title: rig.view === "custom" ? "Custom: the direction is this angle alone." : "Added to the preset direction." });
    labelled(ctx, view, "Reference", select(ctx, { id: "mv-follow-frame" }, [["stage", t(ctx, "Stage front")], ["member", t(ctx, "Member facing")]],
      rig.frame, (value) => setField(ctx, rig.id, "frame", value)));
    if (rig.frame === "member") slider(ctx, refs, view, rig, "turnDamping");
    labelled(ctx, view, "Camera angle", select(ctx, { id: "mv-follow-angle", title: t(ctx, "Fixed: the camera keeps its direction and only follows the member's position. Pan: the camera stays where the rig starts and only turns toward the member. Look at member: it moves and turns.") },
      [["fixed", t(ctx, "Fixed (follow position only)")], ["pan", t(ctx, "Pan (follow angle only)")], ["look", t(ctx, "Look at member")]],
      rig.angle, (value) => setField(ctx, rig.id, "angle", value)));

    // Placement and framing.
    const place = section(ctx, root, "Placement");
    const framing = ctx.make("div", null, { class: "mv-follow-presets", role: "group", "aria-label": t(ctx, "Framing") });
    framing.append(ctx.make("span", t(ctx, "Framing"), { class: "mv-follow-preset-label" }));
    for (const id of Object.keys(FRAMINGS)) {
      const control = ctx.button(t(ctx, FRAMING_LABELS[id]), () => setFraming(ctx, rig.id, id), { "data-mv-follow-framing": id });
      control.disabled = locked;
      framing.append(control);
    }
    place.parentNode.insertBefore(framing, place);
    slider(ctx, refs, place, rig, "distance");
    slider(ctx, refs, place, rig, "height", { title: "Camera height above the look-at point." });
    slider(ctx, refs, place, rig, "lateral", { title: "+ moves the camera toward the member's right in the front view (the camera's left)." });
    slider(ctx, refs, place, rig, "aimHeight", { title: "Moves the point the camera looks at, in the reference frame." });
    slider(ctx, refs, place, rig, "aimSide", { title: "Moves the point the camera looks at, in the reference frame." });
    slider(ctx, refs, place, rig, "aimForward", { title: "Moves the point the camera looks at, in the reference frame." });

    // Lens.
    const lens = section(ctx, root, "Lens");
    slider(ctx, refs, lens, rig, "fov");
    slider(ctx, refs, lens, rig, "roll");

    // Dead zone.
    const dead = section(ctx, root, "Dead zone",
      "Small moves inside the dead zone are ignored. Once the member leaves it, the camera follows until the member is back within radius × (1 − hysteresis).");
    slider(ctx, refs, dead, rig, "radius");
    slider(ctx, refs, dead, rig, "band");
    slider(ctx, refs, dead, rig, "hysteresis");

    // Height lock.
    const lock = section(ctx, root, "Height lock", "Keeps the camera or the look-at point at one height, so jumps and crouches do not bob the camera.");
    labelled(ctx, lock, "Lock", select(ctx, { id: "mv-follow-lock" }, LOCKS.map((id) => [id, t(ctx, LOCK_LABELS[id])]), rig.heightLock.mode,
      (value) => setField(ctx, rig.id, "heightLock.mode", value)));
    if (rig.heightLock.mode !== "off") {
      const fixed = rig.heightLock.value !== "start";
      labelled(ctx, lock, "Locked height", select(ctx, { id: "mv-follow-lock-value" },
        [["start", t(ctx, "Height at the rig start")], ["fixed", t(ctx, "Fixed height")]], fixed ? "fixed" : "start", (value) => {
          const current = findRig(ctx, rig.id);
          if (!current) return;
          if (value === "start") setField(ctx, rig.id, "heightLock.value", "start");
          else {
            // Starts from the height the lock holds now: the look-at point's (aim) or the camera's,
            // at the rig start (the y of the first grid sample).
            const result = stateOf(ctx).evals.get(rig.id)?.result;
            const source = result ? (current.heightLock.mode === "aim" ? result.aims : result.positions) : null;
            const start = source ? Math.round(source[1] * 100) / 100 : 1.4;
            setField(ctx, rig.id, "heightLock.value", clamp(start, ...LIMITS["heightLock.value"]));
          }
        }));
      if (fixed) slider(ctx, refs, lock, rig, "lockValue");
    }

    // Damping.
    const damping = section(ctx, root, "Damping",
      "How long the camera takes to catch up, in seconds (about 63 % of the way). 0 follows at once; larger values are smoother.");
    for (const name of ["aimXZ", "aimY", "bodyXZ", "bodyY"]) slider(ctx, refs, damping, rig, name);

    // Blend.
    const blend = section(ctx, root, "Blend", "Fades from the shot's own camera and back. 0 is a cut.");
    slider(ctx, refs, blend, rig, "blendIn");
    slider(ctx, refs, blend, rig, "blendOut");

    refs.status = ctx.make("div", null, { class: "mv-follow-status", id: "mv-follow-status", "aria-live": "polite" });
    root.append(refs.status);
    root.append(ctx.make("p", t(ctx, "The follow camera is baked for the current members and outfits. Other MV decks can frame differently. For registered MVs, Height lock: Camera is recommended."),
      { class: "mv-field-note mv-follow-notice", id: "mv-follow-notice" }));
    return refs;
  }

  // Status: bake progress with Cancel, a cancelled bake with Bake again, and why a rig is not applied.
  function syncStatus(ctx) {
    const state = stateOf(ctx), refs = state.panel && state.panel.refs;
    if (!refs || !refs.status) return;
    const box = refs.status, lines = [];
    const running = progress(ctx);
    if (running) {
      const line = ctx.make("p", null, { class: "mv-follow-progress", id: "mv-follow-progress" });
      const bar = ctx.make("progress", null, { max: "100", value: String(running.percent), "aria-hidden": "true" });
      line.append(ctx.make("span", format(ctx, "Baking camera… {percent}%", { percent: running.percent })), bar,
        ctx.button(t(ctx, "Cancel"), () => cancel(ctx), { id: "mv-follow-cancel" }));
      lines.push(line);
    } else if (state.cancelled && state.dirty) {
      const line = ctx.make("p", null, { class: "mv-follow-progress mv-follow-warning", id: "mv-follow-cancelled" });
      const again = ctx.button(t(ctx, "Bake again"), () => { state.cancelled = false; requestBake(ctx, "follow"); renderPanel(ctx); }, { id: "mv-follow-rebake" });
      again.disabled = ctx.locked();
      line.append(ctx.make("span", t(ctx, "Baking was cancelled. The shots keep their previous camera.")), again);
      lines.push(line);
    } else if (state.retry) {
      lines.push(ctx.make("p", t(ctx, "Waiting for the 3D preview…"), { class: "mv-field-note" }));
    }
    const rig = selectedRig(ctx);
    if (rig) {
      const missing = state.unavailable.get(rig.id);
      if (missing) lines.push(ctx.make("p", t(ctx, missing.reason), { class: "mv-follow-warning", id: "mv-follow-unavailable" }));
      const evaluated = state.evals.get(rig.id);
      if (rig.frame === "member" && evaluated && !evaluated.facing) {
        lines.push(ctx.make("p", t(ctx, "This member has no facing; the stage front is used."), { class: "mv-follow-warning" }));
      }
      const keys = Keys();
      if (keys && !keys.mainCameraShots(ctx).some(({ event }) => overlaps(rig, event.start, event.start + event.duration))) {
        lines.push(ctx.make("p", t(ctx, "No camera shot is under this rig, so it moves nothing."), { class: "mv-follow-warning" }));
      }
    }
    const focused = global.document && box.contains(document.activeElement) ? document.activeElement.id : null;
    box.replaceChildren(...lines);
    if (focused) box.querySelector("#" + focused)?.focus({ preventScroll: true });
  }

  const round = (value, digits) => finite(value) ? String(Number(value.toFixed(digits))) : "";

  // Values of the built panel (fields keep the user's text while they have the focus).
  function syncPanel(ctx, echo = null) {
    const state = stateOf(ctx), refs = state.panel && state.panel.refs;
    if (!refs) return;
    const rig = selectedRig(ctx);
    if (rig) {
      const focused = global.document ? document.activeElement : null;
      for (const [path, { range, input }] of Object.entries(refs.fields)) {
        const value = path === "start" || path === "end" ? rig[path] : read(rig, path);
        if (!finite(value)) continue;
        const digits = path === "start" || path === "end" ? 3 : 3;
        if (input && (input !== focused || input === echo)) input.value = round(value, digits);
        if (range && range !== focused) range.value = String(value);
      }
    }
    syncStatus(ctx);
  }

  function renderInto(box, ctx) {
    const state = stateOf(ctx);
    watchToggle(ctx, box);
    const rig = ctx.project() ? selectedRig(ctx) : null;
    const key = signature(ctx, rig, members(ctx));
    if (!state.panel || state.panel.box !== box || state.panel.key !== key || !box.contains(state.panel.refs.root)) {
      const active = global.document && document.activeElement;
      const focused = active && box.contains(active) ? (active.dataset && active.dataset.mvFollow ? `[data-mv-follow="${active.dataset.mvFollow}"]`
        : active.dataset && active.dataset.mvFollowView ? `[data-mv-follow-view="${active.dataset.mvFollowView}"]` : active.id ? `#${active.id}` : null) : null;
      state.panel = { box, key, refs: build(ctx, box) };
      syncPanel(ctx);
      if (focused) box.querySelector(focused)?.focus({ preventScroll: true });
      return;
    }
    // Rebuilt pieces that depend on values: the view preset buttons.
    for (const control of box.querySelectorAll("[data-mv-follow-view]")) control.setAttribute("aria-pressed", String(!!rig && rig.view === control.dataset.mvFollowView));
    syncPanel(ctx);
  }

  function watchToggle(ctx, box) {
    const state = stateOf(ctx);
    const details = box && typeof box.closest === "function" ? box.closest("details") : null;
    if (!details || state.toggle === details) return;
    state.toggle = details;
    details.addEventListener("toggle", () => {
      if (details.open && !details.hidden && stateOf(ctx).toggle === details) renderPanel(ctx);
    });
  }

  // ---- plugin ----------------------------------------------------------------------------------------
  // History changes that move a member's path: a performer, or a clip on a followed member's
  // dance or scaling track.
  function pathTouched(ctx, command) {
    const project = ctx.project();
    if (!project || !command || !Array.isArray(command.changes)) return false;
    const rigs = rigsOf(ctx);
    if (!rigs.length) return false;
    const slots = new Set(rigs.map((rig) => rig.target.slot));
    for (const change of command.changes) {
      const target = change.target || {};
      if (target.kind === "performer") return true;
      if (target.kind === "event" || target.kind === "track") {
        const track = project.tracks.find((item) => item.id === target.track);
        if (!track) continue;
        if (track.kind === "dance" && (slots.has(trackSlot(track)) || trackSlot(track) === null)) return true;
        if (track.nativeClass === "LiveMemberScalingTrack") return true;
      }
    }
    return false;
  }

  const rigsChanged = (command) => !!command && Array.isArray(command.changes) && command.changes.some((change) =>
    change.target && change.target.kind === "editor" && Array.isArray(change.path) && change.path[0] === "camera" && (change.path[1] === "rigs" || change.path.length === 1));

  const plugin = {
    id: "camera-follow",
    order: 9,
    attach(ctx) { stateOf(ctx); },
    panels: [{
      key: PANEL, name: "Follow camera", open: false,
      available: (ctx) => panelAvailable(ctx),
      render: (box, ctx) => renderInto(box, ctx),
    }],
    projectChanged(ctx, info = {}) {
      const state = stateOf(ctx);
      if (info.reason === "load") {
        // A project as opened holds its bakes: nothing is sampled or baked on load.
        state.selected = null;
        state.evals.clear();
        state.unavailable.clear();
        state.dirty = false;
        state.cancelled = false;
        state.panel = null;
        for (const task of state.inflight.values()) task.controller.abort();
        if (state.retry) { clearTimeout(state.retry); state.retry = null; }
        state.loads++;
        if (state.unlock) { clearTimeout(state.unlock); state.unlock = null; }
      } else if (info.reason === "history") {
        // The camera keys plugin rebakes after camera edits too; a rig change asks explicitly.
        if (rigsChanged(info.command) || pathTouched(ctx, info.command)) requestBake(ctx, "follow");
        if (state.selected && !findRig(ctx, state.selected)) state.selected = null;
      } else state.panel = null;
      syncLanePresence(ctx);
      drawLane(ctx);
      renderPanel(ctx);
      renderWhenUnlocked(ctx);
    },
    // The rig lane, while the project has rigs (an MV without one keeps its timeline as it was).
    extraLanes(ctx, tab) {
      if (!LANE_TABS.includes(tab)) return [];
      const wanted = laneWanted(ctx);
      stateOf(ctx).laneListed = wanted;
      if (!wanted) return [];
      const rigs = rigsOf(ctx);
      return [{ id: LANE, after: mainTrackId(ctx), label: t(ctx, "Camera rigs (editor)"),
        title: t(ctx, "Follow cameras are editor rigs. They are baked into the camera shots they cover, which is what the game plays."),
        members: [...new Set(rigs.map((rig) => rig.target.slot))],
        render: (lane, layout) => drawLane(ctx, lane, layout) }];
    },
    editedCount(ctx) { return rigsOf(ctx).length; },
    async beforeSave(ctx) { await settle(ctx, false); },
    async beforeExport(ctx) { await settle(ctx, true); },
  };

  // Before a save or export: a bake that is due (cancelled or skipped) runs now; one cancelled
  // again refuses. An export also refuses a rig that has no member to follow.
  async function settle(ctx, exporting) {
    const state = stateOf(ctx), keys = Keys();
    if (!keys || !ctx.project()) return;
    await keys.pending(ctx);
    const active = rigsOf(ctx).filter((rig) => keys.mainCameraShots(ctx).some(({ track, event }) => {
      const shot = keys.shotInfo(ctx, track, event);
      return shot && layer.affects(ctx, shot) && overlapsShot(rig, shot);
    }));
    if (!active.length) return;
    if (state.dirty) {
      state.saving = true;
      try {
        state.cancelled = false;
        await requestBake(ctx, exporting ? "export" : "save");
      } finally { state.saving = false; }
      if (state.dirty) throw new Error("Baking the follow camera was cancelled. Try again to bake it, or delete the rig.");
    }
    if (exporting && active.some((rig) => state.unavailable.has(rig.id))) {
      throw new Error("A follow camera has no member to follow. Choose a loaded member or delete the rig before exporting.");
    }
  }

  // Every UI string of this module (English sources of webtools/i18n.py).
  const STRINGS = Object.freeze([
    "Follow camera", "Camera rigs (editor)",
    "Follow cameras are editor rigs. They are baked into the camera shots they cover, which is what the game plays.",
    "Add follow camera", "Follow camera {index}", "{label} copy",
    "Makes a camera that follows a member, like a Cinemachine follow camera. It covers the shot at the playhead.",
    "No members to follow. Add a performer first.", "Rig", "Rig name", "Time range", "Start (s)", "End (s)", "Duplicate rig", "Delete rig",
    "Target", "Member", "Body part", ...Object.values(PART_LABELS),
    "Camera view", "Front puts the camera on the audience side; Right is the member's right.", ...Object.values(VIEW_LABELS),
    "Custom: the direction is this angle alone.", "Added to the preset direction.",
    "Reference", "Stage front", "Member facing", "Camera angle", "Fixed (follow position only)", "Pan (follow angle only)", "Look at member",
    "Fixed: the camera keeps its direction and only follows the member's position. Pan: the camera stays where the rig starts and only turns toward the member. Look at member: it moves and turns.",
    "Placement", "Framing", ...Object.values(FRAMING_LABELS),
    "Camera height above the look-at point.", "+ moves the camera toward the member's right in the front view (the camera's left).",
    "Moves the point the camera looks at, in the reference frame.", "Lens", "Dead zone",
    "Small moves inside the dead zone are ignored. Once the member leaves it, the camera follows until the member is back within radius × (1 − hysteresis).",
    "Height lock", "Keeps the camera or the look-at point at one height, so jumps and crouches do not bob the camera.",
    "Lock", ...Object.values(LOCK_LABELS), "Locked height", "Height at the rig start", "Fixed height",
    "Damping", "How long the camera takes to catch up, in seconds (about 63 % of the way). 0 follows at once; larger values are smoother.",
    "Blend", "Fades from the shot's own camera and back. 0 is a cut.",
    ...Object.values(FIELDS).map((field) => field[1]),
    "The follow camera is baked for the current members and outfits. Other MV decks can frame differently. For registered MVs, Height lock: Camera is recommended.",
    "Baking camera… {percent}%", "Cancel", "Bake again", "Baking was cancelled. The shots keep their previous camera.",
    "Waiting for the 3D preview…", "The 3D preview is not available, so the follow camera cannot be baked.",
    "This member is not loaded in the 3D preview.", "This member has no target for the chosen body part.",
    "This member has no facing; the stage front is used.", "No camera shot is under this rig, so it moves nothing.",
    "{label} · {start}–{end} · Member {slot}",
    "Baking the follow camera was cancelled. Try again to bake it, or delete the rig.",
    "A follow camera has no member to follow. Choose a loaded member or delete the rig before exporting.",
    "Edit follow camera", "Move follow camera", "Resize follow camera", "Duplicate follow camera", "Delete follow camera",
  ].filter((value, index, list) => list.indexOf(value) === index));

  if (global.MVStudioCameraKeys && typeof global.MVStudioCameraKeys.registerLayer === "function") global.MVStudioCameraKeys.registerLayer(layer);
  (global.MVStudioPlugins ||= []).push(plugin);
  global.MVStudioCameraFollow = Object.freeze({
    plugin, layer, STRINGS, DEFAULTS, LIMITS, VIEWS, VIEW_YAW, LOCKS, FRAMINGS,
    // Model and evaluation (also used by the tests).
    normalizeRig, evaluateRig, poseAt, weight, mix, lookRotation, alpha, frameRange, pathKey, stable,
    // Commands.
    rigs: (ctx) => rigsOf(ctx).map(clone), addRig, deleteRig, duplicateRig, setField, setView, setFraming, setRange, selectRig,
    requestBake, cancel,
    state: (ctx) => { const state = stateOf(ctx); return { dirty: state.dirty, cancelled: state.cancelled, selected: state.selected,
      unavailable: [...state.unavailable.keys()], cache: state.cache.size, progress: progress(ctx) }; },
  });
})(typeof window !== "undefined" ? window : globalThis);
