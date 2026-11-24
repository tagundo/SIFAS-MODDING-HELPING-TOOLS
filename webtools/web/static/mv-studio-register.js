/* MV Studio plugin: "MV 전용 곡으로 등록" — register the open project in the game as an MV-only song.
 *
 * The server (webtools/core/mv_studio_register.py) plans, bakes Android and iOS timelines from
 * the posted project, encodes audio and writes the game catalog in one job. This page only:
 *  - asks for the plan (no writes) when the panel opens and after edits (debounced 1 s);
 *  - calls every plugin's beforeExport(ctx) and the optional prepareNativeExport(ctx, project)
 *    hook ({project?, unbaked?: [{kind, eventId, reason}]}) before posting a project;
 *  - decodes project audio with OfflineAudioContext at 44.1 kHz stereo, trims or pads the
 *    soundtrack offset, and uploads 16-bit PCM WAV to /api/mv-studio/pcm;
 *  - offers a square crop box for a non-square jacket (the server cuts exact pixels);
 *  - lists registered songs with open, fix and remove.
 */
(function (global) {
  "use strict";

  const route = "/api/mv-studio/";
  const RATE = 44100;
  const PCM_LIMIT = 96 * 1024 * 1024;
  const KEY = "register";
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const text = (value) => String(value == null ? "" : value);
  let ctx = null, box = null;
  let state = fresh(), songs = { region: null, list: null, error: "", loading: null, encoder: false, managed: false };

  function fresh() {
    return { plan: null, planning: null, timer: 0, planError: "", target: undefined, template: null, title: null,
      credit: null, jacket: null, jacketInfo: null, crop: null, audio: null, bpm: null, firstBeat: null,
      previewStart: null, segments: null, acb: "", awb: "", download: null, picker: null, job: null, result: null,
      confirm: null, removing: null, charts: { templates: [], template: "", path: "", busy: false }, error: "" };
  }

  // ---- small helpers --------------------------------------------------------------------
  function t(label) { return ctx.t(label); }
  function format(label, values) { return ctx.format(label, values); }
  // Attributes whose value is undefined or null are left out (setAttribute would write "undefined").
  function clean(attrs) {
    const result = {};
    for (const [key, value] of Object.entries(attrs || {})) if (value !== undefined && value !== null) result[key] = value;
    return result;
  }
  function make(tag, label, attrs) { return ctx.make(tag, label, clean(attrs)); }
  function button(label, action, attrs) { return ctx.button(t(label), action, clean(attrs)); }
  function url(path) {
    const language = typeof ctx.language === "function" ? ctx.language() : "en";
    return route + path + (path.includes("?") ? "&" : "?") + "lang=" + encodeURIComponent(language);
  }
  async function call(path, payload, signal) {
    const response = await fetch(url(path), payload === undefined ? { signal, credentials: "same-origin" } : {
      method: "POST", credentials: "same-origin", signal, headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload) });
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok || !data || data.error) throw new Error(data && data.error || "The MV request failed.");
    return data;
  }
  function minutes(seconds) {
    const total = Math.max(0, Math.round(seconds || 0));
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  }
  function message(item) {
    return item && item.values ? format(item.message, item.values) : t(item && item.message || "");
  }
  function platformName(platform) { return platform === "ios" ? "iOS" : "Android"; }
  function source() { const project = ctx.project(); return project && project.source || {}; }
  function open() { const panel = box && box.closest("details"); return !!(panel && panel.open); }
  function updateMode() { return !!(state.plan && state.plan.song && state.target !== "new"); }

  // ---- export preparation (camera bakes and other plugins) --------------------------------
  async function prepare() {
    const others = (Array.isArray(global.MVStudioPlugins) ? global.MVStudioPlugins : []).filter((item) => item && item !== plugin);
    for (const other of others) if (typeof other.beforeExport === "function") await other.beforeExport.call(other, ctx);
    let project = copy(ctx.project());
    const unbaked = [];
    const hooks = others.filter((item) => typeof item.prepareNativeExport === "function")
      .map((item) => (value) => item.prepareNativeExport.call(item, ctx, value));
    if (global.MVStudio && typeof global.MVStudio.prepareNativeExport === "function") {
      hooks.push((value) => global.MVStudio.prepareNativeExport(value));
    }
    for (const hook of hooks) {
      const result = await hook(project);
      if (result && result.project && typeof result.project === "object") project = result.project;
      if (result && Array.isArray(result.unbaked)) unbaked.push(...result.unbaked);
    }
    return { project, unbaked };
  }

  // ---- plan ---------------------------------------------------------------------------------
  function schedulePlan(delay = 1000) {
    if (!ctx.project() || !open()) return;
    clearTimeout(state.timer);
    state.timer = setTimeout(runPlan, delay);
  }

  async function runPlan() {
    if (!ctx.project()) return;
    if (state.planning) state.planning.abort();
    const controller = new AbortController(), current = state;
    state.planning = controller;
    draw();
    try {
      let prepared;
      try { prepared = await prepare(); }
      catch (error) { prepared = null; current.planError = text(error && error.message); }
      if (!prepared) return;
      const body = { project: prepared.project, unbaked: prepared.unbaked };
      if (current.template) body.template = current.template;
      if (current.target !== undefined) body.target = current.target;
      const plan = await call("registration-plan", body, controller.signal);
      if (current !== state) return;
      state.plan = plan;
      state.planError = "";
      applyDefaults(plan);
      if (plan.region && songs.region !== plan.region) loadSongs(plan.region);
    } catch (error) {
      if (error.name !== "AbortError" && current === state) state.planError = text(error.message);
    } finally {
      if (current.planning === controller) current.planning = null;
      if (current === state) draw();
    }
  }

  function applyDefaults(plan) {
    if (state.title === null) state.title = plan.title || "";
    if (state.credit === null) state.credit = plan.credit || "";
    const audio = plan.audio || {};
    const allowed = audioChoices(plan).filter((choice) => !choice.disabled).map((choice) => choice.value);
    if (state.audio === null || !allowed.includes(state.audio)) state.audio = allowed.includes(audio.default) ? audio.default : "base";
    if (audio.beat && state.bpm === null) {
      state.bpm = audio.beat.bpm; state.firstBeat = audio.beat.firstBeat;
      state.segments = audio.beat.segments || null;
    }
    if (state.previewStart === null && Number.isFinite(audio.previewStart)) state.previewStart = audio.previewStart;
    if (state.jacket === null || state.jacket.kind === "keep" && !updateMode()) {
      state.jacket = { kind: updateMode() ? "keep" : "base" };
    }
    if (state.download === null) {
      const project = ctx.project();
      state.download = !!(project && project.source && project.source.download);
    }
  }

  function audioChoices(plan) {
    const audio = plan && plan.audio || {}, soundtrack = audio.soundtrack;
    const choices = [{ value: "base", label: "Original song audio" }];
    if (plan && plan.song) choices.push({ value: "keep", label: "Keep the registered audio" });
    choices.push({ value: "project", label: "Project audio", disabled: !audio.encoder || !soundtrack,
      note: !audio.encoder ? "This version can register only the original audio or prepared ACB/AWB files." :
        !soundtrack ? "This project has no soundtrack." : "" });
    choices.push({ value: "files", label: "Prepared ACB/AWB (advanced)" });
    return choices;
  }

  // ---- songs --------------------------------------------------------------------------------
  async function loadSongs(region) {
    region = region || songs.region || state.plan && state.plan.region || source().region || "gl";
    if (songs.loading) songs.loading.abort();
    const controller = new AbortController();
    songs.loading = controller;
    try {
      const data = await call("songs?region=" + encodeURIComponent(region), undefined, controller.signal);
      songs = { ...songs, region: data.region, list: data.songs || [], error: "", loading: null, encoder: !!data.encoder,
        managed: !!data.managedRestart };
    } catch (error) {
      if (error.name === "AbortError") return;
      songs = { ...songs, region, list: null, error: text(error.message), loading: null };
    }
    draw();
  }

  // ---- audio --------------------------------------------------------------------------------
  function wav(buffer) {
    const frames = buffer.length, channels = 2, bytes = frames * channels * 2;
    const output = new DataView(new ArrayBuffer(44 + bytes));
    const ascii = (offset, value) => { for (let index = 0; index < value.length; index++) output.setUint8(offset + index, value.charCodeAt(index)); };
    ascii(0, "RIFF"); output.setUint32(4, 36 + bytes, true); ascii(8, "WAVEfmt ");
    output.setUint32(16, 16, true); output.setUint16(20, 1, true); output.setUint16(22, channels, true);
    output.setUint32(24, RATE, true); output.setUint32(28, RATE * channels * 2, true);
    output.setUint16(32, channels * 2, true); output.setUint16(34, 16, true); ascii(36, "data"); output.setUint32(40, bytes, true);
    const left = buffer.getChannelData(0), right = buffer.numberOfChannels > 1 ? buffer.getChannelData(1) : left;
    let offset = 44;
    for (let index = 0; index < frames; index++) {
      for (const sample of [left[index], right[index]]) {
        const value = Math.max(-1, Math.min(1, sample || 0));
        output.setInt16(offset, Math.round(value < 0 ? value * 32768 : value * 32767), true);
        offset += 2;
      }
    }
    return output.buffer;
  }

  // Audio time = director time + offset: trim the first offset seconds, or pad silence before a negative one.
  async function soundtrackPcm(soundtrack, signal) {
    const Context = global.OfflineAudioContext || global.webkitOfflineAudioContext;
    const unreadable = new Error("This browser cannot open this audio format. Convert it to WAV and import it again.");
    if (!Context) throw unreadable;
    const response = await fetch(soundtrack.url, { signal, credentials: "same-origin" });
    if (!response.ok) throw new Error("The project soundtrack is no longer available. Import it again.");
    let decoded;
    try { decoded = await new Context(2, 1, RATE).decodeAudioData(await response.arrayBuffer()); }
    catch (_) { throw unreadable; }
    const offset = Number(soundtrack.offset) || 0;
    const shift = Math.round(Math.abs(offset) * RATE);
    const frames = offset >= 0 ? decoded.length - shift : decoded.length + shift;
    if (frames <= 0) throw new Error("The soundtrack offset leaves no audio to register.");
    if (frames * 4 + 44 > PCM_LIMIT) throw new Error("The converted audio is empty or larger than 96 MiB.");
    const context = new Context(2, frames, RATE);
    const node = context.createBufferSource();
    node.buffer = decoded;
    node.connect(context.destination);
    if (offset >= 0) node.start(0, offset); else node.start(-offset);
    return wav(await context.startRendering());
  }

  async function uploadPcm(soundtrack, signal) {
    const data = await soundtrackPcm(soundtrack, signal);
    const response = await fetch(url("pcm"), { method: "POST", credentials: "same-origin", signal,
      headers: { "Content-Type": "audio/wav" }, body: data });
    let result = null;
    try { result = await response.json(); } catch (_) {}
    if (!response.ok || !result || result.error) throw new Error(result && result.error || "The MV request failed.");
    return result.name;
  }

  // ---- register / update ---------------------------------------------------------------------
  function platformsFor(plan) {
    const bake = plan.timeline && plan.timeline.bake || [];
    const needed = state.download ? [] : (plan.timeline && plan.timeline.download || []);
    return { send: bake.filter((platform) => !needed.includes(platform)), skipped: needed.filter((platform) => bake.includes(platform)) };
  }

  function submit(mode) {
    const plan = state.plan;
    if (!plan || state.job || plan.blocked.length) return;
    const title = text(state.title).trim();
    if (!title || title.length > 160) { state.error = "Enter a song title between 1 and 160 characters."; draw(); focus("mv-register-title"); return; }
    const { skipped } = platformsFor(plan);
    if (skipped.length && !(state.confirm && state.confirm.accepted)) {
      state.confirm = { mode, message: skipped.length > 1 ? "Android and iOS will play the original MV. Continue?" :
        skipped[0] === "ios" ? "iOS will play the original MV. Continue?" : "Android will play the original MV. Continue?" };
      draw();
      return;
    }
    state.confirm = null;
    startJob(mode, title);
  }

  async function startJob(mode, title) {
    const plan = state.plan, controller = new AbortController(), current = state;
    state.job = { controller, stage: "Preparing the project", index: 0, total: 1, id: null, events: null };
    state.error = "";
    state.result = null;
    draw();
    try {
      const prepared = await prepare();
      if (prepared.unbaked.length) throw new Error("Some editor changes are not baked into the timeline yet. Wait for them to finish, then register again.");
      const audio = { kind: state.audio };
      if (state.audio === "project") {
        state.job.stage = "Decoding the soundtrack";
        draw();
        audio.pcm = await uploadPcm(plan.audio.soundtrack, controller.signal);
        audio.bpm = Number(state.bpm); audio.firstBeat = Number(state.firstBeat);
        audio.previewStart = Number(state.previewStart) || 0;
        if (state.segments && plan.audio.beat && Number(state.bpm) === plan.audio.beat.bpm &&
            Number(state.firstBeat) === plan.audio.beat.firstBeat) audio.segments = state.segments;
      } else if (state.audio === "files") {
        audio.acbPath = state.acb;
        if (state.awb) audio.awbPath = state.awb;
      }
      const jacket = state.jacket.kind === "file" ? { kind: "file", path: state.jacket.path, ...(state.crop ? { crop: state.crop } : {}) }
        : { kind: state.jacket.kind };
      const body = { mode, project: prepared.project, title, credit: text(state.credit).trim() || null, jacket, audio,
        platforms: platformsFor(plan).send, download: !!state.download, unbaked: [] };
      if (plan.base && !plan.base.fixed) body.template = { region: plan.region, liveId: plan.base.liveId, assetId: plan.base.assetId };
      if (mode === "update") body.liveId = plan.song.liveId;
      if (current !== state) return;
      const receipt = await call("register-job", body, controller.signal);
      follow(receipt.job_id, current);
    } catch (error) {
      if (current !== state) return;
      state.job = null;
      if (error.name !== "AbortError") state.error = text(error.message);
      draw();
    }
  }

  function follow(id, current) {
    if (!global.EventSource) { current.job = null; current.error = "MV registration progress is unavailable. Reopen this page."; draw(); return; }
    current.job.id = id;
    const events = new global.EventSource("/api/jobs/" + encodeURIComponent(id) + "/events");
    current.job.events = events;
    let finished = false;
    events.onmessage = (raw) => {
      let event;
      try { event = JSON.parse(raw.data); } catch (_) { return; }
      if (event.type === "mv-stage") {
        current.job.stage = event.label; current.job.index = event.index; current.job.total = event.total;
      } else if (event.type === "mv-encode" && current.job) {
        current.job.encode = event.total ? event.done / event.total : 0;
      } else if (event.type === "mv-song") {
        current.result = { kind: event.mode === "new" ? "new" : "update", song: event.song, changed: event.changed,
          restart: event.restart, warnings: event.warnings || [] };
        const project = ctx.project();
        if (project && current === state) project.registration = { region: event.song.region, liveId: event.song.liveId };
        current.target = event.song.liveId;
        // The song now holds this jacket and audio: the next update keeps them unless changed again.
        current.jacket = current.jacketInfo = current.crop = null;
        current.audio = null;
      } else if (event.type === "mv-song-removed") {
        current.removed = event;
      } else if (event.type === "done") {
        finished = true;
        events.close();
        current.job = null;
        if (event.status === "error") current.error = text(event.summary);
        else if (event.status === "cancelled") current.error = "MV registration was cancelled.";
        if (current === state) { loadSongs(songs.region); if (event.status === "done") runPlan(); }
      }
      if (current === state) draw();
    };
    events.onerror = () => {
      if (finished || events.readyState !== global.EventSource.CLOSED) return;
      current.job = null;
      current.error = "MV registration progress was interrupted. Check the songs list.";
      if (current === state) draw();
    };
  }

  function cancelJob() {
    const job = state.job;
    if (!job) return;
    if (job.id) fetch("/api/jobs/" + encodeURIComponent(job.id) + "/cancel", { method: "POST", credentials: "same-origin" }).catch(() => {});
    else job.controller.abort();
  }

  // ---- songs list actions ------------------------------------------------------------------
  async function fix(song) {
    if (state.job) return;
    const controller = new AbortController(), current = state;
    state.job = { controller, stage: "Writing to the game catalog", index: 0, total: 1, id: null };
    draw();
    try {
      const receipt = await call("register-job", { mode: "update", region: song.region, liveId: song.liveId, addPlaceholder: true },
        controller.signal);
      follow(receipt.job_id, current);
    } catch (error) {
      current.job = null;
      if (error.name !== "AbortError") current.error = text(error.message);
      draw();
    }
  }

  async function reviewRemove(song) {
    if (state.job) return;
    try {
      const review = await call("songs/remove-plan", { region: song.region, liveId: song.liveId });
      state.removing = { song, review };
    } catch (error) { state.error = text(error.message); }
    draw();
    const dialog = box && box.querySelector("#mv-register-remove-dialog");
    if (dialog) dialog.focus();
  }

  async function remove() {
    const pending = state.removing;
    if (!pending || pending.review.blocked.length || state.job) return;
    state.removing = null;
    const controller = new AbortController(), current = state;
    state.job = { controller, stage: "Removing the song from the game", index: 0, total: 1, id: null };
    draw();
    try {
      const receipt = await call("songs/remove-job", { region: pending.song.region, liveId: pending.song.liveId,
        reviewToken: pending.review.reviewToken }, controller.signal);
      follow(receipt.job_id, current);
    } catch (error) {
      current.job = null;
      if (error.name !== "AbortError") current.error = text(error.message);
      draw();
    }
  }

  function openSong(song) {
    if (typeof ctx.importGame !== "function" || ctx.locked()) return;
    const platform = ["android", "ios"].includes(source().platform) ? source().platform : "android";
    ctx.importGame({ region: song.region, platform, liveId: song.liveId, assetId: song.assetId, download: false });
  }

  // ---- base MV picker (mod and from-scratch projects) ------------------------------------
  async function loadCatalog() {
    const picker = state.picker;
    if (!picker) return;
    if (picker.request) picker.request.abort();
    const controller = new AbortController();
    picker.request = controller;
    try {
      const query = new URLSearchParams({ region: picker.region, platform: "android", search: picker.search });
      const data = await call("catalog?" + query, undefined, controller.signal);
      picker.songs = (data.songs || []).filter((song) => !song.mvOnly);
      picker.regions = data.regions || picker.regions;
      if (!picker.songs.some((song) => song.id === picker.song)) picker.song = picker.songs[0] ? picker.songs[0].id : null;
      const song = picker.songs.find((item) => item.id === picker.song);
      if (!song || !song.variants.some((item) => item.id === picker.variant)) picker.variant = song && song.variants[0] ? song.variants[0].id : null;
      picker.error = "";
    } catch (error) {
      if (error.name === "AbortError") return;
      picker.error = text(error.message);
    } finally {
      if (picker.request === controller) picker.request = null;
    }
    draw();
  }

  // ---- jacket -------------------------------------------------------------------------------
  function chooseJacket() {
    if (typeof ctx.pickFile !== "function") return;
    const current = state;
    ctx.pickFile(async (path) => {
      if (current !== state) return;
      try {
        const info = await call("jacket-preview", { path });
        state.jacket = { kind: "file", path };
        state.jacketInfo = info;
        const side = Math.min(info.width, info.height);
        state.crop = info.square ? null : { x: Math.floor((info.width - side) / 2), y: Math.floor((info.height - side) / 2), size: side };
        state.error = "";
      } catch (error) { state.error = text(error.message); }
      draw();
    }, t("Choose jacket image"), ["png", "jpg", "jpeg", "webp", "bmp", "gif"]);
  }

  function cropControl(info) {
    const crop = state.crop, frame = make("div", null, { class: "mv-register-crop", id: "mv-register-crop" });
    const image = make("img", null, { src: info.previewUrl, alt: t("Jacket"), draggable: "false" });
    const square = make("div", null, { class: "mv-register-crop-box", role: "slider", tabindex: "0",
      "aria-label": t("Choose the square area for the jacket."), "aria-valuetext": `${crop.x}, ${crop.y} · ${crop.size}px` });
    const place = () => {
      square.style.left = (crop.x / info.width * 100) + "%";
      square.style.top = (crop.y / info.height * 100) + "%";
      square.style.width = (crop.size / info.width * 100) + "%";
      square.style.height = (crop.size / info.height * 100) + "%";
      square.setAttribute("aria-valuetext", `${crop.x}, ${crop.y} · ${crop.size}px`);
    };
    const clampCrop = () => {
      crop.size = Math.max(1, Math.min(Math.round(crop.size), info.width, info.height));
      crop.x = Math.max(0, Math.min(Math.round(crop.x), info.width - crop.size));
      crop.y = Math.max(0, Math.min(Math.round(crop.y), info.height - crop.size));
      place();
    };
    square.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const start = { x: event.clientX, y: event.clientY, cropX: crop.x, cropY: crop.y };
      const scale = info.width / frame.getBoundingClientRect().width;
      square.setPointerCapture(event.pointerId);
      const move = (next) => { crop.x = start.cropX + (next.clientX - start.x) * scale; crop.y = start.cropY + (next.clientY - start.y) * scale; clampCrop(); };
      const end = () => { square.removeEventListener("pointermove", move); square.removeEventListener("pointerup", end); square.removeEventListener("pointercancel", end); };
      square.addEventListener("pointermove", move);
      square.addEventListener("pointerup", end);
      square.addEventListener("pointercancel", end);
    });
    square.addEventListener("keydown", (event) => {
      const step = event.shiftKey ? 10 : 1, moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (!moves[event.key]) return;
      event.preventDefault();
      crop.x += moves[event.key][0]; crop.y += moves[event.key][1];
      clampCrop();
    });
    frame.style.aspectRatio = `${info.width} / ${info.height}`;
    frame.append(image, square);
    place();
    const size = make("input", null, { type: "range", id: "mv-register-crop-size", min: "1", max: String(Math.min(info.width, info.height)),
      step: "1", "aria-label": t("Jacket area size") });
    size.value = String(crop.size);
    size.addEventListener("input", () => {
      const centerX = crop.x + crop.size / 2, centerY = crop.y + crop.size / 2;
      crop.size = Number(size.value); crop.x = centerX - crop.size / 2; crop.y = centerY - crop.size / 2;
      clampCrop();
    });
    const wrapper = make("div", null, { class: "mv-register-crop-wrap" });
    wrapper.append(frame, ctx.field("Jacket area size", size),
      make("p", t(crop.size === 400 ? "The selected area is used as is." : "The selected area is resized to 400×400."), { class: "mv-field-note" }));
    return wrapper;
  }

  // ---- rendering ----------------------------------------------------------------------------
  function focus(id) { setTimeout(() => { const node = box && box.querySelector("#" + id); if (node) node.focus(); }); }

  function draw() {
    if (!box || !ctx) return;
    const active = document.activeElement && box.contains(document.activeElement) ? document.activeElement : null;
    const restore = active && active.id ? { id: active.id, start: active.selectionStart, end: active.selectionEnd } : null;
    box.replaceChildren(...content());
    if (restore) {
      const node = box.querySelector("#" + restore.id);
      if (node) {
        node.focus();
        try { if (restore.start != null) node.setSelectionRange(restore.start, restore.end); } catch (_) {}
      }
    }
  }

  function content() {
    const nodes = [], project = ctx.project();
    if (!project) return [make("p", t("No MV is open."))];
    const plan = state.plan, busy = !!state.job;
    if (!plan) {
      nodes.push(make("p", t(state.planError || (state.planning ? "Checking what reaches the game…" : "Open this panel to check what reaches the game.")),
        { class: state.planError ? "mv-register-error" : "mv-field-note", id: "mv-register-status" }));
      nodes.push(songsSection());
      return nodes;
    }
    nodes.push(make("p", format("Region: {region}", { region: text(plan.region).toUpperCase() }), { class: "mv-field-note", id: "mv-register-region" }));
    // Target: a new song or an update of a song made from the same base MV.
    if (plan.targets.length) {
      const target = make("select", null, { id: "mv-register-target" });
      target.append(new Option(t("New song"), "new"));
      for (const song of plan.targets) target.append(new Option(format("Update {title} ({id})", { title: song.title, id: song.liveId }), String(song.liveId)));
      target.value = updateMode() ? String(plan.song.liveId) : "new";
      target.disabled = busy;
      target.addEventListener("change", () => {
        state.target = target.value === "new" ? "new" : Number(target.value);
        state.title = state.credit = null; state.audio = null; state.jacket = null;
        runPlan();
      });
      nodes.push(ctx.field("Register as", target));
      if (!updateMode()) {
        nodes.push(make("p", format("Songs registered from this base MV: {songs}", {
          songs: plan.targets.map((song) => `${song.title} (${song.liveId})`).join(", ") }), { class: "mv-field-note" }));
      }
    }
    nodes.push(baseSection(plan, busy));
    const title = make("input", null, { type: "text", id: "mv-register-title", maxlength: "160", required: "" });
    title.value = text(state.title);
    title.disabled = busy;
    title.addEventListener("input", () => { state.title = title.value; });
    nodes.push(ctx.field("Title", title));
    const credit = make("input", null, { type: "text", id: "mv-register-credit", maxlength: "200",
      placeholder: t("Leave empty to use the base song's credit.") });
    credit.value = text(state.credit);
    credit.disabled = busy;
    credit.addEventListener("input", () => { state.credit = credit.value; });
    nodes.push(ctx.field("Credit", credit));
    nodes.push(jacketSection(plan, busy), audioSection(plan, busy), checkSection(plan, busy));
    nodes.push(actions(plan, busy));
    if (state.confirm) nodes.push(confirmBox());
    if (state.job) nodes.push(progressBox());
    if (state.error) nodes.push(make("p", t(state.error), { class: "mv-register-error", role: "alert", id: "mv-register-error" }));
    if (state.result) nodes.push(resultBox(state.result));
    nodes.push(songsSection(), chartsSection(plan, busy));
    return nodes;
  }

  function baseSection(plan, busy) {
    const section = make("div", null, { class: "mv-register-base" });
    const label = plan.base ? `${plan.base.title}${plan.base.stage ? " · " + plan.base.stage : ""} (${plan.base.liveId})` : t("Not chosen");
    const row = make("div", null, { class: "mv-controls" });
    row.append(make("span", label, { id: "mv-register-base" }));
    // Game imports keep their own base; a registered song whose base is unknown can only be removed.
    const choosable = plan.base ? !plan.base.fixed : !plan.song;
    if (choosable) {
      row.append(button(plan.base ? "Change" : "Choose base MV", () => {
        state.picker = state.picker || { region: plan.region || "gl", search: "", songs: [], regions: [], song: null, variant: null, error: "" };
        loadCatalog();
        draw();
      }, { id: "mv-register-base-change", disabled: busy ? "" : undefined }));
    }
    section.append(ctx.field("Base MV", row),
      make("p", t("Stage, choreography, props and members come from the base MV."), { class: "mv-field-note" }));
    if (state.picker && choosable) section.append(pickerBox(state.picker));
    return section;
  }

  function pickerBox(picker) {
    const fieldset = make("fieldset", null, { id: "mv-register-picker" });
    fieldset.append(make("legend", t("Choose base MV")));
    const region = make("select", null, { id: "mv-register-base-region" });
    for (const item of picker.regions.length ? picker.regions : [{ value: "gl", label: "Global (GL)" }, { value: "jp", label: "Japan (JP)" }]) {
      region.append(new Option(t(item.label), item.value));
    }
    region.value = picker.region;
    region.addEventListener("change", () => { picker.region = region.value; loadCatalog(); });
    const search = make("input", null, { type: "search", id: "mv-register-base-search", placeholder: t("Search MV") });
    search.value = picker.search;
    let timer = 0;
    search.addEventListener("input", () => { picker.search = search.value; clearTimeout(timer); timer = setTimeout(loadCatalog, 300); });
    const song = make("select", null, { id: "mv-register-base-song" });
    for (const item of picker.songs) song.append(new Option(`${item.title} (${item.id})`, String(item.id)));
    if (picker.song != null) song.value = String(picker.song);
    song.addEventListener("change", () => {
      picker.song = Number(song.value);
      const chosen = picker.songs.find((item) => item.id === picker.song);
      picker.variant = chosen && chosen.variants[0] ? chosen.variants[0].id : null;
      draw();
    });
    const variant = make("select", null, { id: "mv-register-base-variant" });
    const chosen = picker.songs.find((item) => item.id === picker.song);
    for (const item of chosen ? chosen.variants : []) variant.append(new Option(t(item.label), String(item.id)));
    if (picker.variant != null) variant.value = String(picker.variant);
    variant.addEventListener("change", () => { picker.variant = Number(variant.value); });
    const use = button("Use this base MV", () => {
      if (picker.song == null || picker.variant == null) return;
      state.template = { region: picker.region, liveId: picker.song, assetId: picker.variant };
      state.picker = null;
      state.target = undefined;
      runPlan();
    }, { id: "mv-register-base-use" });
    use.disabled = picker.song == null || picker.variant == null;
    fieldset.append(ctx.field("Game region", region), ctx.field("Search MV", search), ctx.field("Song", song),
      ctx.field("Stage", variant), use);
    if (picker.error) fieldset.append(make("p", t(picker.error), { class: "mv-register-error" }));
    return fieldset;
  }

  function jacketSection(plan, busy) {
    const fieldset = make("fieldset", null, { id: "mv-register-jacket" });
    fieldset.append(make("legend", t("Jacket")));
    const kind = state.jacket ? state.jacket.kind : "base";
    const row = make("div", null, { class: "mv-controls" });
    const choose = button("Choose image", chooseJacket, { id: "mv-register-jacket-choose" });
    const base = button("Use the base jacket", () => { state.jacket = { kind: "base" }; state.jacketInfo = state.crop = null; draw(); },
      { id: "mv-register-jacket-base", "aria-pressed": String(kind === "base") });
    row.append(choose, base);
    if (plan.song) {
      row.append(button("Keep the registered jacket", () => { state.jacket = { kind: "keep" }; state.jacketInfo = state.crop = null; draw(); },
        { id: "mv-register-jacket-keep", "aria-pressed": String(kind === "keep") }));
    }
    for (const control of row.querySelectorAll("button")) control.disabled = busy || control === choose && typeof ctx.pickFile !== "function";
    fieldset.append(row);
    const info = state.jacketInfo;
    if (kind === "file" && info) {
      fieldset.append(make("p", `${info.name} · ${info.width}×${info.height}`, { class: "mv-field-note", id: "mv-register-jacket-name" }));
      if (info.square) {
        fieldset.append(make("img", null, { src: info.previewUrl, alt: t("Jacket"), class: "mv-register-jacket", id: "mv-register-jacket-image" }));
        fieldset.append(make("p", t(info.exact ? "This 400×400 image is used as is." : "This square image is resized to 400×400."), { class: "mv-field-note" }));
      } else {
        fieldset.append(make("p", t("Choose the square area for the jacket."), { class: "mv-field-note" }), cropControl(info));
      }
    } else {
      fieldset.append(make("p", t(kind === "keep" ? "The registered jacket stays." : "The base song's jacket is used."), { class: "mv-field-note" }));
    }
    fieldset.append(make("p", t("400×400 · choose an area when the image is not square."), { class: "mv-field-note" }));
    return fieldset;
  }

  function numberInput(id, value, attrs, update) {
    const input = make("input", null, { type: "number", id, inputmode: "decimal", ...attrs });
    if (value != null && value !== "") input.value = String(value);
    input.addEventListener("input", () => { update(input.value === "" ? null : input.valueAsNumber); syncSubmit(); });
    return input;
  }

  function audioSection(plan, busy) {
    const fieldset = make("fieldset", null, { id: "mv-register-audio" });
    fieldset.append(make("legend", t("Audio")));
    const soundtrack = plan.audio && plan.audio.soundtrack;
    for (const choice of audioChoices(plan)) {
      const label = make("label", null, { class: "mv-register-choice" });
      const radio = make("input", null, { type: "radio", name: "mv-register-audio", value: choice.value });
      radio.checked = state.audio === choice.value;
      radio.disabled = busy || !!choice.disabled;
      radio.addEventListener("change", () => { if (radio.checked) { state.audio = choice.value; draw(); } });
      let caption = t(choice.label);
      if (choice.value === "project" && soundtrack) caption += ` · ${minutes((soundtrack.duration || 0) - (soundtrack.offset || 0))}`;
      label.append(radio, make("span", caption));
      fieldset.append(label);
      if (choice.disabled && choice.note) fieldset.append(make("p", t(choice.note), { class: "mv-field-note" }));
      if (choice.value === "project" && state.audio === "project") {
        const grid = make("div", null, { class: "mv-register-audio-fields" });
        grid.append(ctx.field("BPM", numberInput("mv-register-bpm", state.bpm, { min: "1", max: "999", step: "any" }, (value) => { state.bpm = value; })),
          ctx.field("First beat (s)", numberInput("mv-register-first-beat", state.firstBeat, { min: "0", step: "any" }, (value) => { state.firstBeat = value; })),
          ctx.field("Preview start (s)", numberInput("mv-register-preview-start", state.previewStart, { min: "0", step: "any" }, (value) => { state.previewStart = value; })));
        if (soundtrack && soundtrack.offset) grid.append(make("p", format("The soundtrack offset ({offset} s) is applied to the registered audio.", { offset: soundtrack.offset }), { class: "mv-field-note" }));
        fieldset.append(grid);
      }
      if (choice.value === "files" && state.audio === "files") {
        const row = make("div", null, { class: "mv-controls" });
        for (const [kind, title, extension] of [["acb", "Choose ACB", "acb"], ["awb", "Choose AWB", "awb"]]) {
          row.append(button(title, () => ctx.pickFile && ctx.pickFile((path) => { state[kind] = path; draw(); }, t(title), [extension]),
            { id: "mv-register-" + kind, disabled: busy ? "" : undefined }));
          if (state[kind]) row.append(make("span", text(state[kind]).split(/[\\/]/).pop(), { class: "mv-field-note", title: state[kind] }));
        }
        fieldset.append(row);
      }
    }
    return fieldset;
  }

  function checkSection(plan) {
    const fieldset = make("fieldset", null, { id: "mv-register-check" });
    fieldset.append(make("legend", t("What reaches the game")));
    const list = make("ul", null, { id: "mv-register-plan", class: "mv-register-plan" });
    const item = (kind, label, extra) => {
      const row = make("li", null, { class: "mv-register-" + kind, "data-mv-plan": kind });
      row.append(make("span", kind === "ok" ? "✓" : kind === "blocked" ? "✕" : "⚠", { "aria-hidden": "true", class: "mv-register-icon" }), make("span", label));
      if (extra) row.append(extra);
      list.append(row);
      return row;
    };
    const edits = plan.edits || {}, timeline = plan.timeline || {};
    if (timeline.native) {
      if (timeline.pending) item("warn", t("The edits are counted once the original MV is available. Allow the download to bake them."));
      else if (timeline.unchanged) item("ok", t("Timeline unchanged: the original MV plays."));
      else {
        if (edits.cameraShots) item("ok", format(edits.follow ? "Camera: {count} shots edited (follow camera included)" : "Camera: {count} shots edited", { count: edits.cameraShots }));
        if (edits.values || edits.timing) item("ok", format("Values: {values} · clip timing: {timing}", { values: edits.values || 0, timing: edits.timing || 0 }));
      }
    } else {
      item("ok", t("No native timeline: the base MV's timeline plays unchanged."));
    }
    const bake = timeline.bake || [], downloads = timeline.download || [];
    if (bake.length) {
      const ready = bake.filter((platform) => !downloads.includes(platform));
      if (ready.length === 2) item("ok", t("Applied on Android and iOS"));
      else if (ready.length === 1) item("ok", format("Applied on {platform}", { platform: platformName(ready[0]) }));
      if (downloads.length) {
        const bytes = downloads.reduce((sum, platform) => sum + (plan.platforms[platform].bytes || 0), 0);
        const check = make("input", null, { type: "checkbox", id: "mv-register-download" });
        check.checked = !!state.download;
        check.addEventListener("change", () => { state.download = check.checked; draw(); });
        const label = make("label", null, { class: "mv-register-download" });
        label.append(check, make("span", format("Download (about {size} MB)", { size: Math.max(0.1, Math.round(bytes / 104857.6) / 10) })));
        item("warn", format("No {platform} original", { platform: downloads.map(platformName).join(" · ") }), label);
      }
    }
    for (const platform of timeline.missing || []) {
      if (timeline.native && !timeline.unchanged) item("warn", format("{platform} has no original in this region: it plays the base MV.", { platform: platformName(platform) }));
    }
    for (const note of plan.notInGame || []) {
      const label = t("Not in the game:") + " " + t(note.message) + (note.labels && note.labels.length ? " " + note.labels.join(", ") : "");
      item("warn", label);
    }
    if ((plan.notInGame || []).length) item("warn", t("Choose outfits in the game's MV deck."));
    for (const warning of plan.warnings || []) item("warn", message(warning));
    for (const blocked of plan.blocked || []) {
      item("blocked", message(blocked) + (blocked.labels && blocked.labels.length ? " " + blocked.labels.join(", ") : ""));
    }
    if (state.planError) item("blocked", t(state.planError));
    fieldset.append(list);
    if (state.planning) fieldset.append(make("p", t("Checking what reaches the game…"), { class: "mv-field-note" }));
    return fieldset;
  }

  // Inputs that the submit button depends on: project audio needs its BPM and first beat, prepared audio its ACB.
  function incomplete() {
    return state.audio === "files" && !state.acb || state.audio === "project" && (!(state.bpm > 0) || !(state.firstBeat >= 0));
  }

  function syncSubmit() {
    const control = box && box.querySelector("#mv-register-submit");
    const plan = state.plan;
    if (!control || !plan) return;
    control.disabled = !!state.job || !!(plan.blocked && plan.blocked.length) || !!state.planError || !!state.planning || incomplete();
  }

  function actions(plan, busy) {
    const row = make("div", null, { class: "mv-controls mv-register-actions" });
    const blocked = !!(plan.blocked && plan.blocked.length) || !!state.planError;
    const invalid = incomplete();
    if (updateMode()) {
      row.append(button("Update song", () => submit("update"), { id: "mv-register-submit", class: "primary" }),
        button("Register as a new song", () => { state.target = "new"; state.jacket = null; state.audio = null; runPlan(); },
          { id: "mv-register-new" }));
    } else {
      row.append(button("Register as an MV-only song", () => submit("new"), { id: "mv-register-submit", class: "primary" }));
    }
    for (const control of row.querySelectorAll("button")) control.disabled = busy || blocked || !!state.planning;
    row.querySelector("#mv-register-submit").disabled ||= invalid;
    return row;
  }

  function confirmBox() {
    const dialog = make("div", null, { class: "mv-register-confirm", role: "alertdialog", id: "mv-register-confirm", tabindex: "-1",
      "aria-label": t(state.confirm.message) });
    const row = make("div", null, { class: "mv-controls" });
    row.append(button("Continue", () => { const mode = state.confirm.mode; state.confirm.accepted = true; submit(mode); }, { id: "mv-register-confirm-yes" }),
      button("Cancel", () => { state.confirm = null; draw(); }, { id: "mv-register-confirm-no" }));
    dialog.append(make("p", t(state.confirm.message)), row);
    return dialog;
  }

  function progressBox() {
    const job = state.job, wrap = make("div", null, { class: "mv-register-progress", id: "mv-register-job" });
    const bar = make("progress", null, { id: "mv-register-progress", max: String(Math.max(1, job.total)) });
    bar.value = Math.min(job.total, job.index + (job.encode || 0));
    const row = make("div", null, { class: "mv-controls" });
    row.append(make("span", t(job.stage) + "…", { id: "mv-register-stage", "aria-live": "polite" }),
      button("Cancel", cancelJob, { id: "mv-register-cancel" }));
    wrap.append(bar, row);
    return wrap;
  }

  function resultBox(result) {
    const wrap = make("div", null, { class: "mv-register-result", id: "mv-register-result", role: "status" });
    const song = result.song;
    if (!result.changed) wrap.append(make("p", t("No changes to apply.")));
    else {
      wrap.append(make("p", "✔ " + format(result.kind === "new" ? "Registered '{title}' ({id})." : "Updated '{title}' ({id}).",
        { title: song.title, id: song.liveId })));
      wrap.append(make("p", t(result.restart === "done" ? "The game server was restarted." :
        result.restart === "pending" ? "The game server restarts when this job finishes." : "Restart the game server to apply it.")));
      wrap.append(make("p", format("In game: Live → song list → {title} → MV", { title: song.title }), { class: "mv-field-note" }));
    }
    for (const warning of result.warnings || []) wrap.append(make("p", t(warning), { class: "mv-field-note" }));
    return wrap;
  }

  function songsSection() {
    const details = make("details", null, { id: "mv-register-songs", class: "mv-register-songs" });
    details.open = !!songs.open;
    details.addEventListener("toggle", () => { songs.open = details.open; if (details.open && !songs.list && !songs.loading) loadSongs(); });
    const list = songs.list || [];
    details.append(make("summary", format("Registered MV-only songs ({count})", { count: list.length })));
    if (songs.error) details.append(make("p", t(songs.error), { class: "mv-register-error" }));
    else if (!songs.list) details.append(make("p", t("Loading…"), { class: "mv-field-note" }));
    else if (!list.length) details.append(make("p", t("No MV-only songs are registered in this region."), { class: "mv-field-note" }));
    const items = make("ul", null, { class: "mv-register-song-list" });
    for (const song of list) {
      const row = make("li", null, { "data-mv-song": String(song.liveId) });
      const head = make("div", null, { class: "mv-register-song-head" });
      head.append(make("strong", song.title), make("span", String(song.liveId), { class: "mv-field-note" }));
      if (song.updatedAt) {
        const date = new Date(song.updatedAt * 1000);
        head.append(make("span", format("Updated {date}", { date: `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}` }), { class: "mv-field-note" }));
      }
      row.append(head);
      const badges = [];
      if (!song.visible) badges.push("Not visible in the game (no Advanced chart)");
      if (song.templateAssetId == null) badges.push("Base MV unknown");
      if (song.platforms && song.platforms.android !== song.platforms.ios) {
        badges.push(song.platforms.ios === "stock" ? "Original MV on iOS" : "Original MV on Android");
      }
      for (const badge of badges) row.append(make("span", "⚠ " + t(badge), { class: "mv-register-badge" }));
      const controls = make("div", null, { class: "mv-controls" });
      const names = { open: "Open", fix: "Fix", remove: "Delete" };
      for (const action of song.actions || []) {
        if (action === "open" && typeof ctx.importGame !== "function") continue;
        const control = button(names[action] || action, () => action === "open" ? openSong(song) : action === "fix" ? fix(song) : reviewRemove(song),
          { "data-mv-song-action": action });
        control.disabled = !!state.job || action === "open" && ctx.locked();
        controls.append(control);
      }
      row.append(controls);
      if (state.removing && state.removing.song.liveId === song.liveId) row.append(removeBox(state.removing));
      items.append(row);
    }
    if (list.length) details.append(items);
    return details;
  }

  function removeBox(pending) {
    const dialog = make("div", null, { class: "mv-register-confirm", role: "alertdialog", id: "mv-register-remove-dialog", tabindex: "-1",
      "aria-label": format("Delete '{title}'?", { title: pending.song.title }) });
    dialog.append(make("p", format("Delete '{title}'?", { title: pending.song.title }), { class: "mv-register-confirm-title" }),
      make("p", t("This deletes the song, its jacket, audio and timeline files, and every player's MV deck, play records and playlist entries for it. A backup is made first, and the game server stops for a moment.")));
    const users = Object.values(pending.review.summary.users || {}).reduce((sum, value) => sum + (Number(value) || 0), 0);
    if (users) dialog.append(make("p", format("Player records to delete: {count}", { count: users }), { class: "mv-field-note" }));
    for (const reason of pending.review.blocked) dialog.append(make("p", t(reason), { class: "mv-register-error", role: "alert" }));
    const row = make("div", null, { class: "mv-controls" });
    const confirm = button("Delete", remove, { "data-mv-remove": "confirm" });
    confirm.disabled = !!pending.review.blocked.length || !!state.job;
    row.append(confirm, button("Cancel", () => { state.removing = null; draw(); }, { "data-mv-remove": "cancel" }));
    dialog.append(row);
    return dialog;
  }

  // Advanced: replace the placeholder Advanced chart or add other difficulties (existing attach flow).
  function chartsSection(plan, busy) {
    const song = state.result && state.result.song || (updateMode() ? plan.song : null);
    if (!song) return document.createDocumentFragment();
    const details = make("details", null, { id: "mv-register-charts" });
    details.open = !!state.charts.open;
    details.addEventListener("toggle", () => { state.charts.open = details.open; });
    details.append(make("summary", t("Advanced: replace charts")),
      make("p", t("Replace the placeholder Advanced chart with your own, or add other difficulties."), { class: "mv-field-note" }));
    const charts = state.charts;
    if (charts.notice) details.append(make("p", t("Chart attached.") + " " + t("Restart the game server to load the updated catalog."),
      { class: "mv-field-note", id: "mv-chart-result", role: "status" }));
    if (!charts.templates.length) {
      const load = button("Load chart templates", async () => {
        charts.busy = true; draw();
        try {
          const query = new URLSearchParams({ region: song.region, liveId: song.liveId });
          const receipt = await call("chart-templates?" + query);
          charts.templates = (receipt.templates || []).filter((item) => Number.isSafeInteger(item.id) && Number.isSafeInteger(item.difficultyType));
          charts.template = charts.templates[0] ? String(charts.templates[0].id) : "";
          if (!charts.templates.length) state.error = "No compatible chart templates.";
        } catch (error) { state.error = text(error.message); }
        charts.busy = false; draw();
      }, { id: "mv-chart-templates" });
      load.disabled = busy || charts.busy;
      details.append(load);
      return details;
    }
    const choices = make("select", null, { id: "mv-chart-template" });
    for (const item of charts.templates) choices.append(new Option(item.label, String(item.id)));
    choices.value = charts.template;
    choices.addEventListener("change", () => { charts.template = choices.value; });
    const pick = button("Choose chart file", () => ctx.pickFile && ctx.pickFile((path) => { charts.path = path; draw(); }, t("Choose chart file"), ["json"]),
      { id: "mv-chart-file" });
    const attach = button("Attach chart", async () => {
      const template = charts.templates.find((item) => String(item.id) === charts.template);
      if (!template || !charts.path) return;
      charts.busy = true; draw();
      try {
        await call("charts", { region: song.region, liveId: song.liveId,
          charts: { [template.difficultyType]: { path: charts.path, template_difficulty_id: template.id } } });
        state.charts = { templates: [], template: "", path: "", busy: false, open: true,
          notice: "Chart attached. Restart the game server to load the updated catalog." };
        state.error = "";
        loadSongs(song.region);
      } catch (error) { state.error = text(error.message); charts.busy = false; }
      draw();
    }, { id: "mv-attach-chart" });
    pick.disabled = busy || charts.busy;
    attach.disabled = busy || charts.busy || !charts.path;
    details.append(ctx.field("Chart template", choices), pick);
    if (charts.path) details.append(make("p", charts.path.split(/[\\/]/).pop(), { title: charts.path }));
    details.append(attach);
    return details;
  }

  const STYLE = `
#mv-panel-register .mv-register-error { color: var(--err, #a22); margin: 0; }
#mv-panel-register .mv-register-plan { list-style: none; padding: 0; margin: 0; display: grid; gap: 4px; }
#mv-panel-register .mv-register-plan li { display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: baseline; }
#mv-panel-register .mv-register-plan li > span:nth-child(2) { flex: 1 1 12em; min-width: 0; }
#mv-panel-register .mv-register-ok .mv-register-icon { color: var(--ok, #2a7); }
#mv-panel-register .mv-register-warn .mv-register-icon { color: var(--warn, #b70); }
#mv-panel-register .mv-register-blocked { color: var(--err, #a22); }
#mv-panel-register .mv-register-choice, #mv-panel-register .mv-register-download { display: flex; gap: 6px; align-items: center; }
#mv-panel-register .mv-register-audio-fields { display: grid; gap: 6px; padding-inline-start: 1.6em; }
#mv-panel-register .mv-register-jacket { width: 96px; height: 96px; object-fit: contain; border: 1px solid var(--line); }
#mv-panel-register .mv-register-crop-wrap { display: grid; gap: 6px; }
#mv-panel-register .mv-register-crop { position: relative; width: 100%; max-width: 320px; touch-action: none; user-select: none; }
#mv-panel-register .mv-register-crop img { display: block; width: 100%; height: 100%; }
#mv-panel-register .mv-register-crop-box { position: absolute; box-sizing: border-box; border: 2px solid var(--accent, #39f);
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, .45); cursor: move; }
#mv-panel-register .mv-register-crop { overflow: hidden; }
#mv-panel-register .mv-register-confirm { border: 1px solid var(--line); border-radius: 6px; padding: 8px; display: grid; gap: 6px;
  background: var(--panel); }
#mv-panel-register .mv-register-confirm-title { font-weight: 600; }
#mv-panel-register .mv-register-progress { display: grid; gap: 4px; }
#mv-panel-register .mv-register-progress progress { width: 100%; }
#mv-panel-register .mv-register-songs summary { padding: 6px 0; }
#mv-panel-register .mv-register-song-list { list-style: none; padding: 0; display: grid; gap: 8px; }
#mv-panel-register .mv-register-song-list li { display: grid; gap: 4px; border-top: 1px solid var(--line); padding-top: 6px; }
#mv-panel-register .mv-register-song-head { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
#mv-panel-register .mv-register-badge { color: var(--warn, #b70); font-size: .76rem; }
#mv-panel-register .mv-register-actions button { flex: 1 1 auto; }
#mv-panel-register button[aria-pressed=true] { border-color: var(--accent, #39f); box-shadow: inset 0 0 0 1px var(--accent, #39f); }
#mv-panel-register input[type=text], #mv-panel-register input[type=search] { min-width: 0; }
`;

  const plugin = {
    id: "mv-studio-register",
    order: 90,
    attach(context) {
      ctx = context;
      if (!document.getElementById("mv-register-style")) {
        const style = document.createElement("style");
        style.id = "mv-register-style";
        style.textContent = STYLE;
        document.head.append(style);
      }
    },
    panels: [{
      key: KEY,
      name: "Register as an MV-only song",
      open: false,
      // Listed for every open project: game imports, saved projects, mods and from-scratch projects.
      available: (context) => !!context.project(),
      render(element) {
        if (box !== element) {
          box = element;
          const panel = element.closest("details");
          if (panel) panel.addEventListener("toggle", () => {
            if (!panel.open) return;
            if (!state.plan && !state.planning) runPlan();
            if (!songs.list && !songs.loading) loadSongs();
          });
        }
        draw();
      },
    }],
    projectChanged(context, { reason }) {
      if (reason === "load") {
        if (state.planning) state.planning.abort();
        clearTimeout(state.timer);
        state = fresh();
        const project = context.project();
        const registration = project && project.registration;
        if (registration && Number.isSafeInteger(registration.liveId)) state.target = undefined;
        draw();
        if (open()) runPlan();
        return;
      }
      schedulePlan(reason === "history" ? 1000 : 0);
    },
  };

  // Every UI string of this module (English sources of webtools/i18n.py).
  const STRINGS = Object.freeze([
    "Register as an MV-only song", "Update song", "Register as a new song", "Base MV", "Choose base MV", "Change",
    "Stage, choreography, props and members come from the base MV.", "Title", "Credit", "Leave empty to use the base song's credit.",
    "Jacket", "Choose image", "Choose jacket image", "Use the base jacket", "Keep the registered jacket",
    "Choose the square area for the jacket.", "Jacket area size", "The selected area is used as is.",
    "The selected area is resized to 400×400.", "This 400×400 image is used as is.", "This square image is resized to 400×400.",
    "The registered jacket stays.", "The base song's jacket is used.", "400×400 · choose an area when the image is not square.",
    "Audio", "Original song audio", "Keep the registered audio", "Project audio", "Prepared ACB/AWB (advanced)",
    "This version can register only the original audio or prepared ACB/AWB files.", "This project has no soundtrack.",
    "BPM", "First beat (s)", "Preview start (s)", "The soundtrack offset ({offset} s) is applied to the registered audio.",
    "Choose ACB", "Choose AWB", "What reaches the game", "Timeline unchanged: the original MV plays.",
    "No native timeline: the base MV's timeline plays unchanged.", "Camera: {count} shots edited",
    "Camera: {count} shots edited (follow camera included)", "Values: {values} · clip timing: {timing}",
    "Applied on Android and iOS", "Applied on {platform}", "Download (about {size} MB)", "No {platform} original",
    "{platform} has no original in this region: it plays the base MV.", "Not in the game:", "Choose outfits in the game's MV deck.",
    "Checking what reaches the game…", "Open this panel to check what reaches the game.", "Region: {region}", "New song",
    "Update {title} ({id})", "Register as", "Songs registered from this base MV: {songs}", "Not chosen", "Game region", "Search MV",
    "Song", "Stage", "Use this base MV", "Continue", "Cancel", "iOS will play the original MV. Continue?",
    "Android will play the original MV. Continue?", "Android and iOS will play the original MV. Continue?",
    "Preparing the project", "Decoding the soundtrack", "Registered '{title}' ({id}).", "Updated '{title}' ({id}).",
    "No changes to apply.", "The game server was restarted.", "The game server restarts when this job finishes.",
    "Restart the game server to apply it.", "In game: Live → song list → {title} → MV", "Registered MV-only songs ({count})",
    "Loading…", "No MV-only songs are registered in this region.", "Updated {date}",
    "Not visible in the game (no Advanced chart)", "Base MV unknown", "Original MV on iOS", "Original MV on Android", "Open", "Fix",
    "Delete", "Delete '{title}'?",
    "This deletes the song, its jacket, audio and timeline files, and every player's MV deck, play records and playlist entries for it. A backup is made first, and the game server stops for a moment.",
    "Player records to delete: {count}", "Advanced: replace charts", "Load chart templates", "Chart template",
    "Replace the placeholder Advanced chart with your own, or add other difficulties.", "Chart attached.",
    "Restart the game server to load the updated catalog.",
    "Choose chart file", "Attach chart", "No compatible chart templates.", "No MV is open.",
    "This browser cannot open this audio format. Convert it to WAV and import it again.",
    "The project soundtrack is no longer available. Import it again.", "The soundtrack offset leaves no audio to register.",
    "The converted audio is empty or larger than 96 MiB.", "MV registration progress is unavailable. Reopen this page.",
    "MV registration progress was interrupted. Check the songs list.", "MV registration was cancelled.",
    "Enter a song title between 1 and 160 characters.",
    "Some editor changes are not baked into the timeline yet. Wait for them to finish, then register again.",
    "The edits are counted once the original MV is available. Allow the download to bake them.",
  ]);

  global.MVStudioRegister = Object.freeze({ STRINGS, wav, platformsFor });
  (global.MVStudioPlugins = global.MVStudioPlugins || []).push(plugin);
})(window);
