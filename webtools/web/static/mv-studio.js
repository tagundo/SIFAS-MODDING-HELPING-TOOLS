/* A separate MV editing session in the shared native asset page. */
(function (global) {
  "use strict";

  const route = "/api/mv-studio/";
  // MV-only song registration is the "register" plugin panel (mv-studio-register.js).
  const panelKeys = ["assets", "performers", "soundtrack", "tracks", "events", "quality", "warnings"];
  const panelNames = ["MV assets", "Performers", "Soundtrack", "Tracks", "Selected event", "MV quality settings", "Import notes"];
  const assetKinds = [
    ["stage", "Stage"], ["background", "Background"], ["outfit", "Performer outfit"],
    ["props", "Props"], ["effect", "Effects"], ["audio", "Soundtrack"], ["other", "Other asset"],
  ];
  const kinds = {
    camera: "Camera", dance: "Dance", mouth: "Mouth", eyes: "Eyes", gaze: "Gaze", cheek: "Cheek",
    sound: "Sound", lighting: "Lighting", display: "Display", bloom: "Bloom", dof: "Depth of field",
    effects: "Effects", stage: "Stage", props: "Props", crowd: "Crowd", split: "Split screen", other: "Other",
  };
  const eventLabels = { fov: "Field of view (FOV)", position: "Position", rotation: "Rotation",
    keyframes: "Keyframes", intensity: "Light intensity", m_Intensity: "Light intensity", paramName: "Parameter name",
    timeScale: "Playback speed", clipIn: "Clip offset (s)", preExtrapolationMode: "Before clip", postExtrapolationMode: "After clip" };
  const eventRanges = {
    fov: [.01, 179.99], clipIn: [0, 3600], timeScale: [.000001, 100], easeIn: [0, 3600], easeOut: [0, 3600],
    blendIn: [-1, 3600], blendOut: [-1, 3600], preExtrapolationTime: [0, 3600], postExtrapolationTime: [0, 3600],
    weight: [0, 1], weightForDirection: [0, 1],
  };
  const byId = (id) => document.getElementById(id);
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const text = (value) => String(value == null ? "" : value);
  const finite = Number.isFinite;
  const basename = (path) => text(path).split(/[\\/]/).pop();
  let settings, scene, project, selected, pending, gameImport, catalogRequest, catalogIndex = [], songs = [];
  let visible = false, playing = false, time = 0, frame = 0, lastFrame = 0, pixelsPerSecond = 1;
  let previewLoading = false, playheadNode, seekInput, timeOutput, lastReadout = -Infinity;
  let hidden = [], assetKind = "stage", performerId = "", resizeObserver, timelineResizer;
  let lastGamePayload = null;
  // Runtime notes from the 3D preview of the open project (for example a
  // depth-of-field clip whose focus target the preview cannot find). They are
  // listed with the project's import notes and never saved into the project.
  let previewWarnings = [], previewWarningsQueued = false, warningsPanelListed = false;
  // Device option of the original client (off by default): Live3DScene requests
  // the display refresh rate instead of the preset's 30/60 fps, and the swing
  // physics step once per frame at that rate.
  let refreshRateMode = 0;
  // Device option of the original client (off by default): the player's
  // anti-aliasing setting lets Max and High 3D draw at the screen height.
  let antiAliasingMode = false;
  // Editor core: undo/redo history, editor plugins (MVStudioPlugins) and the
  // timeline category tabs with their member and name filters.
  const Tabs = global.MVStudioTimelineTabs, Interact = global.MVStudioTimelineInteract;
  const tabKey = "elichika.mv.timelineTab.v1", memberKey = "elichika.mv.timelineMember.v1";
  const searchKey = "elichika.mv.timelineSearch.v1", editableKey = "elichika.mv.timelineEditableOnly.v1";
  let history, ctx, plugins = [], panelList = [], lastPlan = null, lastTimeEmit = 0, renderQueued = 0;
  let preferredTab = "all", activeTab = "all", preferredMember = null, searchText = "", editableOnly = false, groupFilter = "";
  let extrapolationGates = new Map(), trackControls = null;
  const timelineLanes = new Map(), timelineLabels = new Map();
  const audio = document.createElement("audio");
  audio.preload = "metadata";

  function t(label) { return settings.translate(label); }

  // Fills "{name}" placeholders of a translated template.
  function format(label, values) {
    return t(label).replace(/\{(\w+)\}/g, (match, key) => key in values ? String(values[key]) : match);
  }

  // Per-session UI memory (tab and filters). Storage can be missing or throw.
  function session(key, value) {
    try {
      const store = global.sessionStorage;
      if (!store) return null;
      if (value === undefined) return store.getItem(key);
      if (value === null) store.removeItem(key);
      else store.setItem(key, String(value));
    } catch (_) {}
    return null;
  }

  function make(tag, label, attrs = {}) {
    const element = document.createElement(tag);
    if (label != null) element.textContent = label;
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
    return element;
  }

  function button(label, action, attrs) {
    const control = make("button", label, { type: "button", ...attrs });
    control.addEventListener("click", action);
    return control;
  }

  function replaceOptions(select, options, selectedValue, placeholder) {
    select.replaceChildren();
    if (placeholder) select.append(new Option(placeholder, ""));
    for (const item of options) {
      const value = text(typeof item === "object" ? item.id ?? item.value : item);
      if (!value) continue;
      const option = new Option(t(typeof item === "object" ? item.label || value : value), value);
      option.disabled = typeof item === "object" && item.available === false;
      select.append(option);
    }
    if ([...select.options].some((option) => !option.disabled && option.value === text(selectedValue))) select.value = text(selectedValue);
  }

  function formatTime(seconds) {
    const centiseconds = Math.max(0, Math.round(seconds * 100));
    const minutes = Math.floor(centiseconds / 6000);
    const remainder = centiseconds % 6000;
    return `${minutes}:${String(Math.floor(remainder / 100)).padStart(2, "0")}.${String(remainder % 100).padStart(2, "0")}`;
  }

  function report(label, error = false) {
    const status = byId("mv-status");
    status.textContent = label;
    status.hidden = !label;
    status.classList.toggle("mv-error", error);
  }

  function showError(error) {
    if (error && error.name !== "AbortError") report(t(error.message || "The MV could not be loaded."), true);
  }

  function requestURL(path) {
    const delimiter = path.includes("?") ? "&" : "?";
    return route + path + delimiter + "lang=" + encodeURIComponent(settings.language());
  }

  async function request(path, payload, signal) {
    const url = requestURL(path);
    if (global.ElichikaPlatform && ElichikaPlatform.requestJSON) {
      return ElichikaPlatform.requestJSON(url, payload, { signal, maxRequestBytes: 16 * 1024 * 1024, operation: "3D MV" });
    }
    const response = await fetch(url, payload === undefined ? { signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal,
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "The MV request failed.");
    return data;
  }

  // onProgress receives the server's "plan" and "progress" records. They are asked
  // for with ?progress=1, which an older server ignores (it then sends none).
  async function requestGameStream(payload, signal, onStage, onProgress) {
    if (typeof global.TextDecoder !== "function" || typeof global.ReadableStream !== "function" ||
        typeof global.ReadableStream.prototype.getReader !== "function" ||
        typeof global.Response !== "function" || !("body" in global.Response.prototype)) return null;
    const response = await global.fetch(requestURL("game-stream") + (onProgress ? "&progress=1" : ""), {
      method: "POST", credentials: "same-origin", signal,
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(payload),
    });
    if ([404, 405, 501].includes(response.status)) {
      response.body?.cancel?.().catch(() => {});
      return null;
    }
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(data && typeof data.error === "string" && data.error || "The MV request failed.");
    }

    const invalid = () => new Error("The imported MV project is invalid.");
    if (!/^application\/x-ndjson(?:\s*;|$)/i.test(response.headers.get("Content-Type") || "") ||
        !response.body || typeof response.body.getReader !== "function") {
      response.body?.cancel?.().catch(() => {});
      throw invalid();
    }
    const reader = response.body.getReader(), decoder = new global.TextDecoder("utf-8", { fatal: true });
    let buffer = "", scanned = 0, received = 0, stageSeen = false, terminal = null, ended = false;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) {
          ended = true;
          buffer += decoder.decode();
          break;
        }
        received += value.byteLength;
        if (received > 64 * 1024 * 1024) throw invalid();
        buffer += decoder.decode(value, { stream: true });
        // Search only the new text: a multi-megabyte project arrives in many chunks.
        for (let newline; (newline = buffer.indexOf("\n", scanned)) !== -1;) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          scanned = 0;
          if (!line) continue;
          if (terminal) throw invalid();
          let event;
          try { event = JSON.parse(line); } catch (_) { throw invalid(); }
          if (event?.type === "stage" && !stageSeen) {
            const preview = event.preview;
            if (!preview || !Array.isArray(preview.assets) || !Array.isArray(preview.tracks) ||
                !finite(preview.duration) || preview.duration < 0) throw invalid();
            stageSeen = true;
            onStage(preview);
          } else if (event?.type === "complete") {
            terminal = { project: checkedProject(event.project) };
          } else if (event?.type === "error" && typeof event.error === "string" && event.error) {
            terminal = { error: event.error };
          } else if (onProgress && (event?.type === "plan" || event?.type === "progress")) {
            // Showing progress must never fail the import itself.
            try { onProgress(event); } catch (_) {}
          } else throw invalid();
        }
        scanned = buffer.length;
      }
      if (!terminal || buffer.trim()) throw invalid();
      if (terminal.error) throw new Error(terminal.error);
      return terminal.project;
    } finally {
      if (!ended) reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  function resource(path) {
    if (typeof path !== "string" || !path.startsWith("/api/")) return "";
    const resolved = new URL(path, global.location.origin);
    return resolved.origin === global.location.origin ? resolved.href : "";
  }

  function syncPosition(now) {
    if (playheadNode) playheadNode.style.transform = `translateX(${time * pixelsPerSecond}px)`;
    if (now !== undefined && now - lastReadout < 100) return;
    lastReadout = now ?? performance.now();
    seekInput.value = time;
    const label = formatTime(time) + " / " + formatTime(project ? project.duration : 0);
    if (timeOutput.textContent !== label) timeOutput.textContent = label;
  }

  function audioOffset() {
    const offset = project && project.soundtrack && project.soundtrack.offset;
    return finite(offset) ? offset : 0;
  }

  function seek(seconds, changeAudio = true, deferDraw = false) {
    time = clamp(finite(seconds) ? seconds : 0, 0, project ? project.duration : 0);
    if (changeAudio && audio.hasAttribute("src")) audio.currentTime = Math.max(0, time + audioOffset());
    if (scene && project) scene.seek(time, project, deferDraw);
    syncPosition();
    emitTime();
  }

  // timeChanged for plugins: after every seek, at most 10 Hz during playback.
  function emitTime(now) {
    if (!plugins.length) return;
    if (now !== undefined) {
      if (now - lastTimeEmit < 100) return;
      lastTimeEmit = now;
    } else lastTimeEmit = performance.now();
    callPlugins("timeChanged", time, { playing });
  }

  function updatePlayButton() {
    const control = byId("mv-play");
    control.textContent = t(playing ? "Pause" : "Play");
    control.setAttribute("aria-pressed", String(playing));
    const empty = !project || !project.duration;
    control.disabled = empty || previewLoading || !!gameImport;
    byId("mv-rewind").disabled = empty || !!gameImport;
    seekInput.disabled = empty || !!gameImport;
    seekInput.max = project ? project.duration : 0;
  }

  function pause() {
    const wasPlaying = playing;
    playing = false;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    audio.pause();
    if (wasPlaying) {
      scene?.setPlaying?.(false);
      seek(time, false);
    }
    updatePlayButton();
  }

  function tick(now) {
    if (!visible || !playing || !project) return;
    const position = audio.src && !audio.paused && !audio.ended ? audio.currentTime - audioOffset() : time + (now - lastFrame) / 1000;
    lastFrame = now;
    time = clamp(finite(position) ? position : time, 0, project.duration);
    if (scene) scene.playbackFrame(time, now);
    syncPosition(now);
    emitTime(now);
    if (time >= project.duration) pause();
    else frame = requestAnimationFrame(tick);
  }

  function togglePlayback() {
    if (playing) return pause();
    if (!project || !project.duration || !visible || previewLoading || gameImport) return;
    if (time >= project.duration) seek(0);
    playing = true;
    lastFrame = performance.now();
    scene?.setPlaying?.(true);
    if (audio.src) audio.play().catch(() => {
      if (playing) report(t("Soundtrack playback is unavailable. The timeline is still playing."), true);
    });
    updatePlayButton();
    frame = requestAnimationFrame(tick);
  }

  // Built-in panels and the panels editor plugins add right after "Selected event".
  function panelNode(key) {
    const panel = panelList.find((item) => item.key === key);
    return panel && byId(panel.plugin ? "mv-panel-" + key : "mv-" + key);
  }

  function availablePanels() {
    return panelList.filter((panel) => {
      if (panel.plugin) {
        try { return typeof panel.plugin.available !== "function" || !!panel.plugin.available(ctx); } catch (error) { console.error(error); return false; }
      }
      if (panel.key === "warnings") return warningLines().length > 0;
      return true;
    }).map((panel) => panel.key);
  }

  function applyPanels() {
    const active = availablePanels();
    for (const { key } of panelList) panelNode(key).hidden = !active.includes(key) || hidden.includes(key);
    const allHidden = active.every((key) => hidden.includes(key));
    byId("mv-inspector").hidden = allHidden;
    const workspace = byId("mv-workspace");
    const changed = workspace.classList.contains("mv-hide-inspector") !== allHidden;
    workspace.classList.toggle("mv-hide-inspector", allHidden);
    if (changed) timelineResizer?.syncBounds();
    if (visible && scene) scene.resize();
  }

  function renderPanelMenu() {
    const menu = byId("mv-panel-options");
    menu.replaceChildren();
    const panels = availablePanels();
    warningsPanelListed = panels.includes("warnings");
    for (const key of panels) {
      const check = make("input", null, { type: "checkbox", "data-mv-panel-option": key });
      check.checked = !hidden.includes(key);
      const label = make("label");
      label.append(check, make("span", t(panelList.find((panel) => panel.key === key).name)));
      check.addEventListener("change", () => {
        hidden = hidden.filter((id) => id !== key);
        if (!check.checked) hidden.push(key);
        try { localStorage.setItem("elichika.mv.panels.v1", JSON.stringify(hidden)); } catch (_) {}
        applyPanels();
      });
      menu.append(label);
    }
    applyPanels();
  }

  function field(label, value) {
    const row = make("label", null, { class: "mv-field" });
    row.append(make("span", t(label)), value);
    return row;
  }

  function renderAssets() {
    const box = byId("mv-asset-list");
    box.replaceChildren();
    if (!project) { box.append(make("p", t("No MV is open."))); return; }
    const list = make("ul", null, { class: "mv-asset-list" });
    for (const asset of project.assets || []) {
      const item = make("li", text(asset.label || basename(asset.path) || asset.id), { title: text(asset.path) });
      item.append(make("small", [kinds[asset.kind] || assetKinds.find((entry) => entry[0] === asset.kind)?.[1] || asset.kind, asset.status]
        .filter(Boolean).map(t).join(" · ")));
      list.append(item);
    }
    if (list.childElementCount) box.append(list);
    const choice = make("select", null, { id: "mv-asset-kind" });
    replaceOptions(choice, assetKinds.map(([id, label]) => ({ id, label })), assetKind);
    choice.addEventListener("change", () => { assetKind = choice.value; });
    const add = button(t("Import MV asset"), () => importAsset(assetKind), { id: "mv-add-asset" });
    add.disabled = !!pending;
    box.append(field("Asset type", choice), add);
  }

  function renderPerformers() {
    const box = byId("mv-performer-fields"), performers = project && project.performers || [];
    box.replaceChildren();
    if (!performers.length) { box.append(make("p", t("No performers are loaded."))); return; }
    const control = make("select", null, { id: "mv-performer" });
    replaceOptions(control, performers, performerId);
    performerId = control.value;
    const actor = performers.find((item) => text(item.id) === performerId);
    if (!actor) return;
    control.addEventListener("change", () => { performerId = control.value; renderPerformers(); });
    box.append(field("Performer", control));
    const position = actor.transform && actor.transform.position || [0, 0, 0];
    for (const [axis, label] of ["X", "Y", "Z"].entries()) {
      const value = finite(position[axis]) ? position[axis] : 0;
      box.append(field(label, numberInput(value, { min: -1000, max: 1000, "data-mv-performer-axis": label }, (next) => {
        const current = actor.transform && Array.isArray(actor.transform.position) ? actor.transform.position.slice(0, 3) : [];
        const after = [0, 1, 2].map((index) => finite(current[index]) ? current[index] : 0);
        after[axis] = next;
        edit({ label: "Move performer", changes: [{ target: { kind: "performer", id: actor.id }, path: ["transform", "position"], after }] },
          "performers");
      })));
    }
    const costume = gameCostumeControl(actor);
    if (costume) box.append(field("Game costume", costume));
    const change = button(t("Replace outfit"), () => importAsset("outfit", actor.id), { id: "mv-replace-outfit" });
    change.disabled = !!pending;
    box.append(change);
  }

  // The costume override of a game MV member: re-imports the MV with that suit (and
  // m_suit_view model) pinned at the performer's position, keeping earlier pins.
  function gameCostumeControl(actor) {
    const choices = Array.isArray(actor.costumes) ? actor.costumes : [];
    if (!project || project.source?.kind !== "game" || !choices.length || !samePayload(lastGamePayload)) return null;
    const view = (value) => Number.isInteger(value) && value > 1 ? value : 1;
    const options = choices.map((choice, index) => ({ id: String(index), label: text(choice.name || choice.id) + " (" +
      text(choice.id) + (view(choice.viewStatus) > 1 ? " · " + t("View status") + " " + choice.viewStatus : "") + ")" }));
    const control = make("select", null, { id: "mv-performer-costume" });
    const current = choices.findIndex((choice) => choice.id === actor.costumeId && view(choice.viewStatus) === view(actor.viewStatus));
    replaceOptions(control, options, String(current));
    control.disabled = !!pending;
    control.addEventListener("change", () => {
      const choice = choices[Number(control.value)];
      if (!choice) return;
      const costumes = {};
      for (const performer of project.performers || []) {
        if (performer.suitSource === "pinned" && Number.isInteger(performer.costumeId)) {
          costumes[performer.position] = { suit: performer.costumeId, viewStatus: view(performer.viewStatus) };
        }
      }
      costumes[actor.position] = { suit: choice.id, viewStatus: view(choice.viewStatus) };
      runGameImport({ ...lastGamePayload, costumes }, true);
    });
    return control;
  }

  function samePayload(payload) {
    const source = project && project.source || {};
    return !!payload && payload.region === source.region && payload.platform === source.platform &&
      String(payload.liveId) === String(source.liveId) && String(payload.assetId) === String(source.assetId);
  }

  function renderSoundtrack() {
    const box = byId("mv-soundtrack-fields"), soundtrack = project && project.soundtrack;
    box.replaceChildren();
    if (!project) { box.append(make("p", t("No MV is open."))); return; }
    if (soundtrack && soundtrack.url) box.append(field("Soundtrack offset (s)", numberInput(audioOffset(), {
      min: 0, max: 3600, id: "mv-soundtrack-offset",
    }, (next) => edit({ label: "Change soundtrack offset", changes: [{ target: { kind: "soundtrack" }, path: ["offset"], after: next }] },
      "soundtrack"))));
    const change = button(t("Import soundtrack"), () => importAsset("audio"), { id: "mv-import-soundtrack" });
    change.disabled = !!pending;
    box.append(change);
  }

  // Tracks panel: filters that combine with the active timeline tab, and a summary.
  function renderTracks() {
    const box = byId("mv-track-controls");
    box.replaceChildren();
    trackControls = null;
    if (!project || !project.tracks.length) { box.append(make("p", t("No timeline events."))); return; }
    const editable = checkInput(editableOnly, { id: "mv-track-editable-only" }, (value) => {
      editableOnly = value;
      session(editableKey, value ? "1" : null);
      renderTimeline();
    });
    const group = make("select", null, { id: "mv-track-group" });
    group.addEventListener("change", () => { groupFilter = group.value; renderTimeline(); });
    const summary = make("p", null, { id: "mv-track-summary", class: "mv-track-summary", "aria-live": "polite" });
    box.append(field("Show editable tracks only", editable), field("Native group", group), summary);
    trackControls = { editable, group, summary };
    syncTrackControls();
  }

  function syncTrackControls() {
    if (!trackControls || !lastPlan) return;
    replaceOptions(trackControls.group, lastPlan.groups.map((id) => ({ id, label: id })), lastPlan.group, t("All groups"));
    trackControls.editable.disabled = activeTab === "edit";
    trackControls.editable.title = activeTab === "edit" ? t("The Edit tab already lists edited and editable tracks.") : "";
    const edited = history.editedEvents();
    let clips = 0, changed = 0;
    for (const track of lastPlan.tracks) for (const event of track.events) { clips++; if (edited.has(event.id)) changed++; }
    trackControls.summary.textContent = format("{tracks} tracks · {clips} clips · {edited} edited",
      { tracks: lastPlan.tracks.length, clips, edited: changed });
  }

  function activeEvent() {
    if (!selected || !project) return null;
    const track = project.tracks.find((item) => item.id === selected.track);
    const event = track && track.events.find((item) => item.id === selected.event);
    return event ? { track, event } : null;
  }

  function numberInput(value, options, update) {
    const control = make("input", null, { type: "number", step: "any", ...options });
    control.value = value;
    control.addEventListener("change", () => {
      if (control.value !== "" && finite(control.valueAsNumber)) {
        const min = control.hasAttribute("min") ? Number(control.min) : -Infinity;
        const max = control.hasAttribute("max") ? Number(control.max) : Infinity;
        value = clamp(control.valueAsNumber, min, max);
        update(value);
      }
      control.value = value;
    });
    return control;
  }

  function checkInput(value, attrs, update) {
    const control = make("input", null, { type: "checkbox", ...attrs });
    control.checked = Boolean(value);
    control.addEventListener("change", () => update(control.checked));
    return control;
  }

  // write(segments, next) records the edit; segments is the key path under event.values.
  function eventField(object, key, path, editable, depth = 0, segments = [key], write = () => {}) {
    const value = object[key];
    const title = eventLabels[key] || String(key);
    const data = { "data-mv-field": path };
    const update = (next) => write(segments, next);
    if (key === "time" && path.startsWith("keyframes.")) editable = false;
    if (editable && finite(value)) {
      if (key === "preExtrapolationMode" || key === "postExtrapolationMode") {
        const control = make("select", null, data);
        replaceOptions(control, ["None", "Hold", "Loop", "Ping-pong", "Continue"].map((label, id) => ({ id, label })), value);
        control.addEventListener("change", () => update(Number(control.value)));
        return field(title, control);
      }
      const range = eventRanges[key];
      const bounds = range ? { min: range[0], max: range[1] } : {};
      return field(title, numberInput(value, { ...data, ...bounds }, update));
    }
    if (editable && typeof value === "boolean") return field(title, checkInput(value, data, update));
    if (editable && key === "paramName" && typeof value === "string") {
      const control = make("input", null, { type: "text", maxlength: 120, ...data });
      control.value = value;
      control.addEventListener("change", () => update(control.value));
      return field(title, control);
    }
    if (value && typeof value === "object" && depth < 4 && Object.keys(value).length) {
      const group = make("fieldset");
      group.append(make("legend", t(title)));
      if (Array.isArray(value) && value.length && value[0] && typeof value[0] === "object") {
        const body = make("div"), row = (index) => body.replaceChildren(eventField(value, index - 1, path + "." + (index - 1), editable,
          depth + 1, [...segments, index - 1], write));
        const cursor = numberInput(1, { min: 1, max: value.length, step: 1, "aria-label": t("Entry number") }, (index) => row(Math.round(index)));
        group.append(field("Entry number", cursor), body);
        row(1);
      } else for (const key of Object.keys(value).slice(0, 48)) {
        group.append(eventField(value, key, path + "." + key, editable, depth + 1, [...segments, key], write));
      }
      return group;
    }
    return field(title, make("output", typeof value === "object" ? JSON.stringify(value).slice(0, 240) : text(value)));
  }

  function eventTarget(track, event) {
    return { kind: "event", track: track.id, event: event.id };
  }

  function findEvent(trackId, eventId) {
    const track = project && project.tracks.find((item) => item.id === trackId);
    const event = track && track.events.find((item) => item.id === eventId);
    return event ? { track, event } : null;
  }

  function autoExtrapolation(track) {
    const id = track && typeof track === "object" ? track.id : track;
    return extrapolationGates.get(id) === true;
  }

  // Recomputed extrapolation times of a gated track, as history changes.
  function extrapolationWrites(track, overrides) {
    if (!autoExtrapolation(track)) return [];
    return Interact.extrapolationChanges(track, overrides).map((write) => ({
      target: eventTarget(track, write.event), path: ["values", write.key], after: write.value }));
  }

  function writableValue(track, event, key) {
    const editable = track.editable !== false && event.editable !== false;
    if (!editable || (Array.isArray(event.editableValues) && !event.editableValues.includes(key))) return false;
    return !((key === "preExtrapolationTime" || key === "postExtrapolationTime") && autoExtrapolation(track));
  }

  function setEventValue(track, event, segments, next) {
    const changes = [{ target: eventTarget(track, event), path: ["values", ...segments], after: next }];
    if (segments.length === 1 && segments[0] === "postExtrapolationMode" && finite(next)) {
      changes.push(...extrapolationWrites(track, new Map([[event.id, { postMode: next }]])));
    }
    return edit({ label: "Edit value", detail: segments.join("."), changes }, "events");
  }

  // Start/duration change as one command, with the recomputed extrapolation times.
  function timingCommand(track, event, next, label) {
    const target = eventTarget(track, event), changes = [];
    if (finite(next.start) && next.start !== event.start) changes.push({ target, path: ["start"], after: next.start });
    if (finite(next.duration) && next.duration !== event.duration) changes.push({ target, path: ["duration"], after: next.duration });
    if (!changes.length) return null;
    changes.push(...extrapolationWrites(track, new Map([[event.id, { start: next.start, duration: next.duration }]])));
    return { label, changes };
  }

  // move/resize rules of a clip: the editable flags, then every plugin. A drag also
  // waits for a running MV task (transient: not drawn on the clips or the inspector).
  function clipRules(track, event, transient = false) {
    if (transient && ctx.locked()) return { move: false, resize: false, reason: t("Wait for the current MV task to finish.") };
    if (track.editable === false || event.editable === false) return { move: false, resize: false, reason: t("This clip's timing cannot be edited.") };
    const rules = { move: true, resize: true, reason: "" }, reasons = [];
    for (const result of callPlugins("clipConstraints", track, event)) {
      if (!result || typeof result !== "object") continue;
      if (result.move === false) rules.move = false;
      if (result.resize === false) rules.resize = false;
      if ((result.move === false || result.resize === false) && result.reason) reasons.push(String(result.reason));
    }
    rules.reason = reasons.join(" ");
    return rules;
  }

  function renderEventHeader(box, track, event) {
    box.replaceChildren();
    const edited = history.editedEvents().has(event.id);
    const title = make("div", null, { class: "mv-event-title" });
    title.append(make("strong", text(event.label || track.label)));
    if (edited) title.append(make("span", t("Edited"), { class: "mv-edited-badge" }));
    box.append(title);
    const actions = make("div", null, { class: "mv-controls mv-event-actions" });
    if (edited && history.originals.get(event.id)) {
      actions.append(button(t("Revert clip"), () => revertEvent(track, event), { id: "mv-revert-clip" }));
    }
    if (project.nativeTimeline !== true && track.editable !== false && event.editable !== false) {
      actions.append(button(t("Duplicate clip"), () => duplicateEvent(track, event), { id: "mv-duplicate-clip" }),
        button(t("Delete clip"), () => deleteEvent(track, event), { id: "mv-delete-clip" }));
    }
    if (actions.childElementCount) box.append(actions);
  }

  function renderEvent() {
    const box = byId("mv-event-fields");
    const focus = focusedField(box);
    box.replaceChildren();
    const active = activeEvent();
    if (!active) { box.append(make("p", t("Select an event in the timeline."))); return; }
    const { track, event } = active;
    const editable = track.editable !== false && event.editable !== false;
    const header = make("div", null, { class: "mv-event-header", id: "mv-event-header" });
    renderEventHeader(header, track, event);
    box.append(header);
    if (editable) {
      const name = make("input", null, { type: "text", maxlength: 240, "data-mv-field": "label" });
      name.value = text(event.label);
      name.addEventListener("change", () => {
        const next = name.value;
        if (!next.trim() || next.length > 240) { name.value = text(event.label); return; }
        edit({ label: "Rename clip", changes: [{ target: eventTarget(track, event), path: ["label"], after: next }] }, "events");
      });
      box.append(field("Clip name", name));
    }
    const start = text(event.start), duration = text(event.duration), rules = clipRules(track, event);
    if (editable && rules.move !== false) {
      box.append(field("Start time (s)", numberInput(event.start, { "data-mv-field": "start", min: 0, max: project.duration - event.duration }, (value) => {
        const command = timingCommand(track, event, { start: value, duration: event.duration }, "Move clip");
        if (command && edit(command)) seek(value);
      })));
    } else box.append(field("Start time (s)", make("output", start, rules.reason ? { title: rules.reason } : {})));
    if (editable && rules.resize !== false) {
      // At least one frame, as a drag or trim allows.
      box.append(field("Duration (s)", numberInput(event.duration, { "data-mv-field": "duration", min: Interact.FRAME, max: project.duration - event.start }, (value) => {
        const command = timingCommand(track, event, { start: event.start, duration: value }, "Resize clip");
        if (command) edit(command);
      })));
    } else box.append(field("Duration (s)", make("output", duration, rules.reason ? { title: rules.reason } : {})));
    if (rules.reason && (rules.move === false || rules.resize === false)) box.append(make("p", rules.reason, { class: "mv-field-note" }));
    for (const element of callPlugins("eventHeader", { track, event })) if (element) box.append(element);
    const values = event.values || {}, original = history.originals.get(event.id);
    let noted = false;
    for (const key of Object.keys(values).slice(0, 48)) {
      const writable = writableValue(track, event, key);
      const access = valueAccess(track, event, key);
      const info = { track, event, key, path: key, value: values[key], writable,
        original: original && original.values ? original.values[key] : undefined, set: access.set, gesture: access.gesture };
      const control = valueControl(info);
      if (control === null) continue;
      box.append(control !== undefined ? control : eventField(values, key, key, writable, 0, [key], (segments, next) => setEventValue(track, event, segments, next)));
      if (!noted && control === undefined && autoExtrapolation(track) && (key === "preExtrapolationTime" || key === "postExtrapolationTime")) {
        noted = true;
        box.append(make("p", t("Recomputed by the game"), { class: "mv-field-note" }));
      }
    }
    for (const element of callPlugins("eventFooter", { track, event })) if (element) box.append(element);
    restoreFocus(box, focus);
  }

  // Keeps keyboard focus on the same field when the inspector is rebuilt.
  function focusedField(box) {
    const active = document.activeElement;
    return active && box.contains && box.contains(active) && active.dataset && active.dataset.mvField || null;
  }

  function restoreFocus(box, name) {
    if (!name || !box.querySelector) return;
    const control = [...box.querySelectorAll("[data-mv-field]")].find((item) => item.dataset.mvField === name);
    if (control && document.activeElement !== control) control.focus({ preventScroll: true });
  }

  // info.set and info.gesture of one value control. Its sets belong to its own
  // gesture; an edit through any other control closes that gesture first.
  function valueAccess(track, event, key) {
    let token = null;
    const control = {
      set: (next) => {
        const previous = setter;
        setter = control;
        try { return setEventValue(track, event, [key], next); } finally { setter = previous; }
      },
      gesture: {
        // Does nothing while this control's gesture is still open, so it never nests
        // on itself. settings.owner: see gestureBegan.
        begin: (settings) => {
          if (token && history.gestureToken === token) return;
          leaveGesture(control);
          const previous = beginning;
          beginning = control;
          try { token = history.begin("Edit value", settings); } finally { beginning = previous; }
        },
        // The token keeps a late end() (after the host closed a gesture this control
        // left open) from closing a newer gesture.
        end: () => { if (token) history.end(token); },
      },
    };
    return control;
  }

  // A gesture (one undo step) belongs to its owner: the element begin(label,
  // { owner }) names (a popover the user presses several times), else the element
  // pressed while it began, else the focused one (begun from the keyboard). One begun
  // through info.gesture also belongs to that value control. A control can leave a
  // gesture open (a pointer released outside it, a picker closed with no change), so
  // the host closes one once the user moves on:
  //   - at the next primary press, unless begin() named the owner and the press is in it;
  //   - at a key pressed outside the owner (not while typing in a field), and at any
  //     key once the press that began it is over (its picker takes the keys while it
  //     is up), unless begin() named the owner;
  //   - before an edit or info.gesture.begin() through another control.
  // The host never closes a gesture at a release, nor while a press inside its owner
  // lasts, so end() may come on pointerup or, for a control whose UI runs after the
  // release (an <input type=color> picker), on change.
  let press = null, gestureOwner = null, beginning = null, setter = null;

  function gestureBegan(token, settings) {
    const named = settings.owner && typeof settings.owner.contains === "function" ? settings.owner : null;
    const active = document.activeElement;
    const focused = active && active !== document.body && active !== document.documentElement ? active : null;
    // keys: whether keys pressed inside the owner keep the gesture open.
    gestureOwner = { token, named: !!named, keys: !!named || !press, element: named || (press && press.target) || focused, control: beginning };
  }

  function openGesture() {
    const token = history && history.gestureToken;
    if (!token) return null;
    return gestureOwner && gestureOwner.token === token ? gestureOwner : { token, named: false, keys: false, element: null, control: null };
  }

  function inOwner(owner, node) {
    const element = owner.element;
    return !!element && !!node && element.isConnected && (element === node || element.contains(node));
  }

  // The current press (until its release's own handlers ran) is on the owner.
  const pressInOwner = (owner, held = false) => !!press && (!held || press.held) && inOwner(owner, press.target);

  function closeGestures() {
    while (history.gestureActive) history.end();
  }

  // source: the value control an edit or begin() comes through, or null for the
  // host's own controls. A ctx.history.begin() gesture takes every info.set, so a
  // plugin control can put several values in one step.
  function leaveGesture(source) {
    const owner = openGesture();
    if (!owner || pressInOwner(owner) || (owner.control ? owner.control === source : source)) return;
    closeGestures();
  }

  function watchGestures() {
    document.addEventListener("pointerdown", (event) => {
      if (!event.isPrimary) return;
      const owner = openGesture();
      if (owner && !pressInOwner(owner, true) && !(owner.named && inOwner(owner, event.target))) closeGestures();
      press = { target: event.target, pointerId: event.pointerId, held: true };
    }, true);
    // A press lasts until its release's own handlers (pointerup, click, change) ran.
    for (const type of ["pointerup", "pointercancel"]) {
      document.addEventListener(type, (event) => {
        const ended = press;
        if (!event.isPrimary || !ended || ended.pointerId !== event.pointerId) return;
        ended.held = false;
        setTimeout(() => { if (press === ended) press = null; }, 0);
      }, true);
    }
  }

  function valueControl(info) {
    for (const plugin of plugins) {
      if (typeof plugin.valueControl !== "function") continue;
      let result;
      try { result = plugin.valueControl(ctx, info); } catch (error) { console.error(error); continue; }
      if (result !== undefined) return result;
    }
    return undefined;
  }

  function revertEvent(track, event) {
    for (const plugin of plugins) {
      if (typeof plugin.revertEvent !== "function") continue;
      try { if (plugin.revertEvent(ctx, track, event) === true) return; } catch (error) { console.error(error); }
    }
    const original = history.originals.get(event.id);
    if (!original) return;
    const target = eventTarget(track, event), values = copy(original.values || {});
    const changes = [{ target, path: ["start"], after: original.start }, { target, path: ["duration"], after: original.duration },
      { target, path: ["label"], after: original.label }, { target, path: ["values"], after: values }];
    // A gated track's times are recomputed on the reverted state: the original's own
    // stored times are stale once a neighbour has been retimed since it was captured.
    const reverted = { ...event, start: original.start, duration: original.duration, values: copy(values) };
    changes.push(...extrapolationWrites({ ...track, events: track.events.map((item) => item === event ? reverted : item) }, new Map()));
    edit({ label: "Revert clip", changes });
  }

  // Non-native projects only: the exporter refuses new or removed native clips. The copy gets an
  // id the project never held: a deleted clip keeps its id in editor.originals (an added one as
  // null), and editor state kept under that id for undo (a camera record) must not pass to it.
  function duplicateEvent(track, event) {
    if (project.nativeTimeline === true) return;
    const ids = new Set(project.tracks.flatMap((item) => item.events.map((clip) => clip.id)));
    const used = (id) => ids.has(id) || history.originals.get(id) !== undefined;
    let number = 1;
    while (used(`${track.id}:u${number}`)) number++;
    const clone = copy(event);
    clone.id = `${track.id}:u${number}`;
    clone.start = clamp(event.start + event.duration, 0, Math.max(0, project.duration - event.duration));
    delete clone.editable;
    const index = track.events.indexOf(event) + 1;
    const virtual = { ...track, events: [...track.events.slice(0, index), clone, ...track.events.slice(index)] };
    const changes = [{ target: { kind: "track", track: track.id }, path: ["events"], op: "insert", index, value: clone }];
    if (autoExtrapolation(track)) {
      for (const write of Interact.extrapolationChanges(virtual, new Map())) {
        changes.push({ target: eventTarget(track, write.event), path: ["values", write.key], after: write.value });
      }
    }
    if (edit({ label: "Duplicate clip", changes })) {
      const found = findEvent(track.id, clone.id);
      if (found) chooseEvent(found.track, found.event);
    }
  }

  function deleteEvent(track, event) {
    if (project.nativeTimeline === true) return;
    const index = track.events.indexOf(event);
    if (index < 0) return;
    const virtual = { ...track, events: track.events.filter((item) => item !== event) };
    const changes = [{ target: { kind: "track", track: track.id }, path: ["events"], op: "remove", index }];
    if (autoExtrapolation(track)) {
      for (const write of Interact.extrapolationChanges(virtual, new Map())) {
        changes.push({ target: eventTarget(track, write.event), path: ["values", write.key], after: write.value });
      }
    }
    edit({ label: "Delete clip", changes });
  }

  function renderQuality() {
    const box = byId("mv-quality-fields");
    box.replaceChildren();
    const quality = project && project.quality;
    if (!quality || !quality.options || !quality.options.length) { box.append(make("p", t("No MV quality settings were imported."))); return; }
    const modes = quality.modes || [];
    const select = make("select", null, { id: "mv-quality-mode" });
    replaceOptions(select, modes, quality.mode);
    select.addEventListener("change", () => {
      const mode = modes.find((candidate) => text(candidate.id) === select.value);
      if (!mode) return;
      edit({ label: "Change quality preset", changes: [{ target: { kind: "quality" }, path: ["mode"], after: mode.id },
        { target: { kind: "quality" }, path: ["values"], after: { ...quality.values, ...copy(mode.values || {}) } }] });
    });
    if (modes.length) box.append(field("Quality preset", select));
    const mode = modes.find((candidate) => text(candidate.id) === select.value && candidate.description);
    if (mode) box.append(make("p", t(mode.description)));
    const values = quality.values || {};
    for (const option of quality.options) {
      const key = option.key, value = values[key];
      const data = { "data-mv-quality": key };
      const update = (next) => edit({ label: "Change quality setting", detail: text(option.label || key),
        changes: [{ target: { kind: "quality" }, path: ["values", key], after: next }] }, "quality");
      if (option.type === "boolean" || option.type === "checkbox") box.append(field(option.label || key, checkInput(value, data, update)));
      else if (option.type === "number" && finite(value)) box.append(field(option.label || key, numberInput(value, data, update)));
      else if (value != null) box.append(field(option.label || key, make("output", text(value))));
    }
    box.append(field("Anti-aliasing", checkInput(antiAliasingMode, { id: "mv-anti-aliasing" }, (value) => {
      antiAliasingMode = value;
      scene?.setAntiAliasing?.(antiAliasingMode);
    })));
    if (!global.MVStudioPhysics) return;
    const refresh = make("select", null, { id: "mv-refresh-rate-mode" });
    replaceOptions(refresh, [{ id: 0, label: "Off" }, ...global.MVStudioPhysics.REFRESH_RATES.map((rate) => ({ id: rate, label: `${rate} Hz` }))],
      refreshRateMode);
    refresh.addEventListener("change", () => {
      refreshRateMode = Number(refresh.value) || 0;
      applyRefreshRateMode();
      seek(time, false);
    });
    box.append(field("Refresh-rate mode", refresh));
  }

  function applyRefreshRateMode() {
    scene?.setPhysicsTiming?.({ device: refreshRateMode ? { refreshRateMode: true, displayRate: refreshRateMode } : {} });
  }

  function chooseEvent(track, event, move = true) {
    selected = { track: track.id, event: event.id };
    pause();
    if (move) seek(event.start);
    syncClipSelection();
    const panel = byId("mv-events");
    if (!panel.hidden) panel.open = true;
    renderEvent();
    callPlugins("selectionChanged", { track, event });
  }

  function clearSelection() {
    if (!selected) return;
    selected = null;
    syncClipSelection();
    renderEvent();
    callPlugins("selectionChanged", null);
  }

  function syncClipSelection() {
    for (const clip of byId("mv-timeline-grid").querySelectorAll(".mv-clip")) {
      clip.setAttribute("aria-pressed", String(!!selected && clip.dataset.track === text(selected.track) && clip.dataset.event === text(selected.event)));
    }
  }

  function scrub(event, deferDraw = false) {
    if (event.target.closest(".mv-clip, .mv-key, .mv-rig-clip")) return;
    const bar = event.currentTarget;
    seek((event.clientX - bar.getBoundingClientRect().left) / pixelsPerSecond, true, deferDraw);
  }

  function flushScrub() {
    scene?.flushSeekDraw();
  }

  // The lane geometry handed to plugins (laneDecorate, extraLanes).
  function laneLayout(rowOf) {
    const grid = byId("mv-timeline-grid");
    let rowHeight = null;
    return {
      pixelsPerSecond, rowOf, grid, laneLeft: 0,
      get rowHeight() {
        if (rowHeight === null) {
          const lane = grid.querySelector && grid.querySelector(".mv-lane");
          const value = lane && global.getComputedStyle ? parseFloat(global.getComputedStyle(lane).getPropertyValue("--mv-clip-row-height")) : NaN;
          rowHeight = finite(value) ? value : 30;
        }
        return rowHeight;
      },
    };
  }

  // MainCamera cuts (scene rule for camera tracks it renders), playhead and the
  // other clip edges on the same track: snap targets for a clip drag.
  function clipSnapTargets(trackId, eventId) {
    const targets = [time];
    for (const track of project ? project.tracks : []) {
      const camera = track.kind === "camera" && track.nativeClass !== "LiveCameraOffsetTrack" && (!track.binding || /MainCamera/i.test(track.binding));
      if (track.id !== trackId && !camera) continue;
      for (const event of track.events) {
        if (track.id === trackId && event.id === eventId) continue;
        targets.push(event.start, event.start + event.duration);
      }
    }
    return targets;
  }

  function attachClipDrag(clip, trackId, eventId) {
    const place = (range) => {
      clip.style.left = `${range.start * pixelsPerSecond}px`;
      clip.style.width = `${Math.max(13, (range.end - range.start) * pixelsPerSecond)}px`;
    };
    Interact.attachDrag(clip, {
      label: "Move clip",
      pixelsPerSecond: () => pixelsPerSecond,
      getRange: () => {
        const found = findEvent(trackId, eventId);
        return found ? { start: found.event.start, end: found.event.start + found.event.duration } : null;
      },
      bounds: () => ({ min: 0, max: project ? project.duration : 0, minLength: Interact.FRAME }),
      snapTargets: () => clipSnapTargets(trackId, eventId),
      allowed: () => {
        const found = findEvent(trackId, eventId);
        return found ? clipRules(found.track, found.event, true) : { move: false, resize: false };
      },
      setRange: (range, { phase, mode }) => {
        const found = findEvent(trackId, eventId);
        if (!found) return;
        if (phase === "preview") {
          place(range);
          clip.dataset.dragTime = formatTime(mode === "end" ? range.end : range.start);
          return;
        }
        delete clip.dataset.dragTime;
        if (phase === "cancel") { place({ start: found.event.start, end: found.event.start + found.event.duration }); return; }
        const { track, event } = found;
        // The commit can redraw the lane or the whole timeline (an Edit-tab track moves
        // to the edited section): a focused clip keeps the focus for the next nudge.
        const hadFocus = clip === document.activeElement;
        // A move keeps the stored duration exactly (end − start would add float noise).
        const next = mode === "move" ? { start: range.start, duration: event.duration } : { start: event.start, duration: range.end - event.start };
        const command = timingCommand(track, event, next, mode === "move" ? "Move clip" : "Resize clip");
        const changed = !!command && edit(command);
        if (!changed) place({ start: event.start, end: event.start + event.duration });
        const current = findEvent(trackId, eventId);
        if (!current) return;
        if (!selected || selected.track !== trackId || selected.event !== eventId) chooseEvent(current.track, current.event, false);
        if (mode === "move") seek(current.event.start);
        else seek(time, false);
        const again = timelineLanes.get(trackId)?.querySelector?.(`.mv-clip[data-event="${CSS.escape(eventId)}"]`);
        if (hadFocus && again && document.activeElement !== again) focusClip(again);
      },
    });
  }

  // Focus without a jump; with follow, a clip whose lane moved out of view (an Edit-tab
  // reorder) is scrolled back to the nearest edge.
  function focusClip(clip, follow = true) {
    clip.focus({ preventScroll: true });
    if (follow) clip.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }

  function inView(element, box) {
    const a = element.getBoundingClientRect(), b = box.getBoundingClientRect();
    return a.right > b.left && a.left < b.right && a.bottom > b.top && a.top < b.bottom;
  }

  function renderTimelineLane(track) {
    const lane = make("div", null, { class: "mv-lane", "data-kind": text(track.kind), "data-track": text(track.id), "data-tab": Tabs.tabOf(track) });
    lane.addEventListener("click", scrub);
    const rows = [], rowOf = new Map(), edited = history.editedEvents();
    for (const event of track.events.slice().sort((first, second) => first.start - second.start)) {
      const title = text(event.label || track.label || kinds[track.kind]);
      const isSelected = selected && selected.track === track.id && selected.event === event.id;
      const changed = edited.has(event.id);
      const rules = clipRules(track, event);
      const clip = button(title, (click) => { click.stopPropagation(); chooseEvent(track, event); }, {
        class: "mv-clip", title: `${title} · ${formatTime(event.start)}` + (changed ? " · " + t("Edited") : "") + (rules.reason ? " · " + rules.reason : ""),
        "data-track": text(track.id), "data-event": text(event.id), "aria-pressed": String(!!isSelected), "aria-describedby": "mv-clip-help",
      });
      if (changed) { clip.classList.add("mv-edited"); clip.dataset.edited = "true"; }
      if (rules.move === false && rules.resize === false) clip.classList.add("mv-clip-locked");
      else if (rules.resize !== false) clip.classList.add("mv-clip-resizable");
      const left = event.start * pixelsPerSecond, width = Math.max(13, event.duration * pixelsPerSecond);
      const free = rows.findIndex((end) => end + 1 < left), row = free < 0 ? rows.length : free;
      rows[row] = left + width;
      rowOf.set(event.id, row);
      clip.style.left = `${left}px`;
      clip.style.width = `${width}px`;
      clip.style.setProperty("--mv-clip-row", row);
      attachClipDrag(clip, track.id, event.id);
      lane.append(clip);
    }
    lane.style.setProperty("--mv-lane-rows", Math.max(rows.length, 1));
    lane.mvLayout = laneLayout(rowOf);
    return lane;
  }

  function decorateLane(track, lane) {
    callPlugins("laneDecorate", track, lane, lane.mvLayout);
  }

  function refreshTimelineLane(track) {
    const id = track && typeof track === "object" ? track.id : track;
    const previous = timelineLanes.get(id);
    const current = project && project.tracks.find((item) => item.id === id);
    if (!previous || !current) return;
    const focused = previous.contains(document.activeElement) ? document.activeElement.dataset.event : null;
    const lane = renderTimelineLane(current);
    previous.replaceWith(lane);
    timelineLanes.set(id, lane);
    decorateLane(current, lane);
    syncLaneLabel(current);
    if (focused) lane.querySelector(`.mv-clip[data-event="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
  }

  // Edited marks only (a value edit does not move clips): keeps the clip elements and their focus.
  function syncLaneMarks(track) {
    const lane = timelineLanes.get(track.id);
    if (!lane) return;
    const edited = history.editedEvents();
    for (const clip of lane.querySelectorAll(".mv-clip")) {
      const changed = edited.has(clip.dataset.event);
      clip.classList.toggle("mv-edited", changed);
      if (changed) clip.dataset.edited = "true";
      else delete clip.dataset.edited;
    }
    syncLaneLabel(track);
  }

  function syncLaneLabel(track) {
    const label = timelineLabels.get(track.id);
    if (!label) return;
    const edited = history.editedEvents();
    label.classList.toggle("mv-lane-edited", track.events.some((event) => edited.has(event.id)));
  }

  function laneLabel(track) {
    const full = text(track.label || kinds[track.kind] || track.kind);
    const label = make("p", null, { class: "mv-lane-label", title: text(track.binding || track.label), "data-track": text(track.id) });
    const cut = full.lastIndexOf("/"), body = make("span", null, { class: "mv-lane-text" });
    if (cut > 0) {
      // The group path is muted and may wrap after each "/" (<wbr> adds no text).
      const group = make("span", null, { class: "mv-lane-path" });
      for (const part of full.slice(0, cut).split("/")) group.append(part + "/", document.createElement("wbr"));
      body.append(group, make("span", full.slice(cut + 1), { class: "mv-lane-name" }));
    } else body.append(make("span", full, { class: "mv-lane-name" }));
    label.append(body);
    return label;
  }

  function pluginEditCount() {
    let count = 0;
    for (const value of callPlugins("editedCount")) if (finite(value) && value > 0) count += value;
    return count;
  }

  function editCount() {
    return (project ? history.editedEvents().size : 0) + pluginEditCount();
  }

  function tabCounts() {
    const counts = Tabs.census(project ? project.tracks : []);
    const edited = project ? history.editedEvents() : new Set();
    counts.edit = { tracks: project ? project.tracks.filter((track) => track.events.some((event) => edited.has(event.id))).length : 0,
      events: editCount() };
    return counts;
  }

  function selectTab(id, focus) {
    preferredTab = id;
    session(tabKey, id);
    groupFilter = "";
    renderTimeline();
    if (focus) byId("mv-tab-" + activeTab)?.focus();
  }

  function selectMember(value, focus) {
    preferredMember = value === "" || value == null ? null : Number(value);
    session(memberKey, preferredMember === null ? null : preferredMember);
    renderTimeline();
    if (focus) byId("mv-member-filter").querySelector('[aria-checked="true"]')?.focus();
  }

  function renderTimelineTabs() {
    const nav = byId("mv-timeline-nav"), list = byId("mv-timeline-tabs");
    nav.hidden = !project;
    if (!project) { list.replaceChildren(); byId("mv-member-filter").hidden = true; return; }
    const counts = tabCounts(), ids = Tabs.visibleTabs(counts);
    activeTab = ids.includes(preferredTab) ? preferredTab : "all";
    const refocus = list.contains(document.activeElement);
    Tabs.renderTabs(list, {
      active: activeTab, onSelect: selectTab,
      tabs: ids.map((id) => ({ id, label: t(Tabs.TABS.find((tab) => tab.id === id).label), count: counts[id].events,
        tracks: counts[id].tracks })),
      title: (tab) => format("Tracks: {tracks} · Clips: {clips}", { tracks: tab.tracks, clips: tab.count }),
    });
    if (refocus) byId("mv-tab-" + activeTab)?.focus({ preventScroll: true });
  }

  function renderMemberFilter(plan) {
    const box = byId("mv-member-filter");
    box.hidden = !plan.memberTracks;
    if (!plan.memberTracks) { box.replaceChildren(); return; }
    const refocus = box.contains(document.activeElement);
    const choices = [{ value: "", label: t("All members") }];
    for (const member of Tabs.memberChoices(project)) {
      const generic = t("Member") + " " + member.slot;
      choices.push({ value: member.slot, label: member.name ? `${member.slot} · ${member.name}` : generic,
        title: member.name ? `${generic} · ${member.name}` : generic, color: member.color });
    }
    Tabs.renderChips(box, { choices, active: plan.member === null ? "" : plan.member, onSelect: selectMember });
    if (refocus) box.querySelector('[aria-checked="true"]')?.focus({ preventScroll: true });
  }

  // Tracks that hold edited clips, plus the plugin lanes of the Edit tab.
  let lastEditSignature = "";
  function editSignature() {
    if (!project) return "";
    const edited = history.editedEvents();
    const ids = project.tracks.filter((track) => track.events.some((event) => edited.has(event.id))).map((track) => track.id);
    return ids.join("\n") + "|" + (activeTab === "edit" ? extraLanes("edit").map((lane) => lane.id).join("\n") + "|" + (pluginEditCount() > 0) : "");
  }

  function extraLanes(tab) {
    const lanes = [];
    for (const list of callPlugins("extraLanes", tab)) if (Array.isArray(list)) lanes.push(...list.filter((lane) => lane && lane.id != null));
    return lanes;
  }

  function wideRow(className, label, attrs = {}) {
    const row = make("div", null, { class: className, ...attrs });
    row.append(make("span", label));
    return row;
  }

  function renderTimeline() {
    const grid = byId("mv-timeline-grid"), scroll = byId("mv-timeline-scroll");
    // A rebuild keeps keyboard focus on the same clip, wherever its lane lands; the view
    // follows it only if it was in view (a resize does not scroll back to a far clip).
    const active = document.activeElement;
    const focused = active && active !== grid && grid.contains(active) && active.classList.contains("mv-clip")
      ? { track: active.dataset.track, event: active.dataset.event, follow: inView(active, scroll) } : null;
    grid.replaceChildren();
    timelineLanes.clear();
    timelineLabels.clear();
    playheadNode = null;
    lastPlan = null;
    renderTimelineTabs();
    if (!project) {
      scroll.removeAttribute("role");
      scroll.removeAttribute("aria-labelledby");
      return;
    }
    const heading = make("p", t("Tracks"), { class: "mv-lane-label" });
    const ruler = make("div", null, { class: "mv-ruler" });
    const scale = byId("mv-zoom").value;
    grid.append(heading, ruler);
    const duration = Math.max(1, project.duration);
    pixelsPerSecond = scale === "fit" ? Math.max(.1, (scroll.clientWidth - heading.offsetWidth) / duration) : Number(scale);
    grid.style.setProperty("--mv-grid-width", `${Math.round(pixelsPerSecond * duration)}px`);
    const interval = [0.5, 1, 2, 5, 10, 15, 30, 60].find((value) => value * pixelsPerSecond >= 56) || 120;
    grid.style.setProperty("--mv-tick-width", `${interval * pixelsPerSecond}px`);
    for (let mark = 0; mark <= project.duration; mark += interval) {
      const item = make("span", formatTime(mark).replace(/\.00$/, ""));
      item.style.left = `${mark * pixelsPerSecond}px`;
      ruler.append(item);
    }
    ruler.addEventListener("pointerdown", (event) => { ruler.setPointerCapture(event.pointerId); scrub(event, true); });
    ruler.addEventListener("pointermove", (event) => { if (ruler.hasPointerCapture(event.pointerId)) scrub(event, true); });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) ruler.addEventListener(type, flushScrub);
    // A remembered member that this MV does not have is ignored (and kept for the next MV).
    const member = Tabs.memberChoices(project).some((choice) => choice.slot === preferredMember) ? preferredMember : null;
    const plan = Tabs.plan(project.tracks, { tab: activeTab, member, search: searchText,
      editableOnly: activeTab !== "edit" && editableOnly, group: groupFilter, edited: history.editedEvents(), extra: extraLanes(activeTab),
      pluginEdits: activeTab === "edit" ? pluginEditCount() : 0 });
    lastPlan = plan;
    lastEditSignature = editSignature();
    groupFilter = plan.group;
    const decorate = [];
    for (const row of plan.rows) {
      if (row.type === "track") {
        const label = laneLabel(row.track), lane = renderTimelineLane(row.track);
        timelineLanes.set(row.track.id, lane);
        timelineLabels.set(row.track.id, label);
        grid.append(label, lane);
        syncLaneLabel(row.track);
        decorate.push([row.track, lane]);
      } else if (row.type === "group") {
        grid.append(make("p", text(row.track.label), { class: "mv-lane-label mv-lane-group", title: text(row.track.label), "data-track": text(row.track.id) }),
          make("div", null, { class: "mv-lane-group-lane", "aria-hidden": "true" }));
      } else if (row.type === "extra") {
        const label = make("p", text(row.lane.label), { class: "mv-lane-label mv-lane-extra-label", title: text(row.lane.title || row.lane.label) });
        const lane = make("div", null, { class: "mv-lane mv-lane-extra", "data-extra": text(row.lane.id) });
        lane.addEventListener("click", scrub);
        grid.append(label, lane);
        try { row.lane.render?.(lane, laneLayout(new Map())); } catch (error) { console.error(error); }
      } else if (row.type === "separator") {
        grid.append(wideRow("mv-lane-separator", t("Editable"), { role: "presentation" }));
      } else if (row.type === "hint") {
        grid.append(wideRow("mv-lane-hint", t("No edits yet. Editable tracks are listed below.")));
      }
    }
    for (const [track, lane] of decorate) decorateLane(track, lane);
    renderMemberFilter(plan);
    playheadNode = make("div", null, { class: "mv-playhead", "aria-hidden": "true" });
    grid.append(playheadNode);
    scroll.setAttribute("role", "tabpanel");
    scroll.setAttribute("aria-labelledby", "mv-tab-" + activeTab);
    syncTrackControls();
    syncPosition();
    const clip = focused && grid.querySelector(`.mv-clip[data-track="${CSS.escape(focused.track)}"][data-event="${CSS.escape(focused.event)}"]`);
    if (clip) focusClip(clip, focused.follow);
  }

  function renderPreviewStatus() {
    const hint = byId("mv-empty-preview");
    const hasModels = !!(scene && project && (project.stage?.glb || (project.performers || []).some((actor) => actor.glb) ||
      (project.assets || []).some((asset) => ["effect", "props", "background"].includes(asset.kind) && asset.previewUrl)));
    const loading = previewLoading || !!gameImport;
    hint.textContent = t(loading ? "Loading 3D model…" : project ? "This MV has no visual assets available for preview." : "Open an MV to preview its stage and timeline.");
    // A game import shows its progress card instead.
    hint.hidden = !!gameImport || hasModels && !loading;
    byId("mv-preview-controls").hidden = !hasModels || loading;
  }

  function warningLines() {
    return project ? [...(project.warnings || []), ...previewWarnings] : [];
  }

  function renderWarnings() {
    byId("mv-warning-list").replaceChildren(...warningLines().map((line) => make("li", t(line))));
  }

  // The scene reports these from inside its own draw (MVStudioDofFocus.sample
  // runs in renderView and playbackFrame). Opening the warnings panel resizes
  // the scene, and a resize draws, so the list and the panel update once the
  // current call stack has returned, never inside the draw that reported.
  function previewWarning(message) {
    if (typeof message !== "string" || !message || previewWarnings.includes(message) || previewWarnings.length >= 64) return;
    previewWarnings.push(message);
    if (previewWarningsQueued) return;
    previewWarningsQueued = true;
    Promise.resolve().then(() => {
      previewWarningsQueued = false;
      renderWarnings();
      if (!warningsPanelListed && warningLines().length) renderPanelMenu();
    });
  }

  // ---- Editor core: history, plugins, shortcuts ----------------------------------------
  //
  // Editor plugins load before this file and register with
  //   (window.MVStudioPlugins ||= []).push({ id, order, ...hooks });
  // mount() sorts them by order then id and calls attach(ctx) once. Hooks (all optional):
  //   panels [{ key, name, open, available(ctx), render(box, ctx) }]  → <details id="mv-panel-<key>">
  //   projectChanged(ctx, { reason: "load"|"reload"|"reimport"|"history", command?, direction? })
  //   timeChanged(ctx, time, { playing })        selectionChanged(ctx, { track, event } | null)
  //   valueControl(ctx, info) → Element | null (hide) | undefined (built-in field)
  //   eventHeader / eventFooter(ctx, { track, event }) → Element | undefined
  //   laneDecorate(ctx, track, lane, layout)     extraLanes(ctx, tabId) → [{ id, after, label, title, render(lane, layout), members? }]
  //   clipConstraints(ctx, track, event) → { move?: false, resize?: false, reason? }
  //   revertEvent(ctx, track, event) → true when handled    editedCount(ctx) → number
  //   keydown(ctx, KeyboardEvent) → true when handled        beforeSave / beforeExport(ctx) → Promise; throw to refuse
  // Writes go through ctx.history (MVStudioEditHistory); a write made outside it (a
  // derived bake) is followed by ctx.refreshLane(trackId). A gesture makes one undo
  // step: begin() on pointerdown, end() on pointerup/pointercancel or, when the
  // control's UI runs after the release (an <input type=color> picker), on change.
  // history.begin(label, { owner }?) and info.gesture.begin({ owner }?) open one (the
  // latter does nothing while its own gesture is open); history.begin() returns a token
  // object, history.end(token) ignores a gesture that is already closed, and end()
  // with no token (or an Event) ends the open one. The host closes a gesture left open
  // once the user moves on (see gestureBegan).

  function callPlugins(hook, ...args) {
    const results = [];
    for (const plugin of plugins) {
      if (typeof plugin[hook] !== "function") continue;
      try { results.push(plugin[hook](ctx, ...args)); } catch (error) { console.error(`MV Studio plugin ${plugin.id}: ${hook}`, error); }
    }
    return results;
  }

  // Applies one history command. quiet names the panel the edit came from: that
  // panel keeps its controls (and focus) instead of being rebuilt.
  let quietPanel = null;
  function edit(command, quiet = null) {
    if (!history || !project) return false;
    leaveGesture(setter);
    const previous = quietPanel;
    quietPanel = quiet;
    try { return history.apply(command); } finally { quietPanel = previous; }
  }

  function undo() { if (project && !ctx.locked()) history.undo(); }
  function redo() { if (project && !ctx.locked()) history.redo(); }

  function updateHistoryButtons() {
    const locked = !project || !!pending || !!gameImport;
    for (const [id, peek, label] of [["mv-undo", history.peekUndo(), "Undo"], ["mv-redo", history.peekRedo(), "Redo"]]) {
      const control = byId(id);
      control.disabled = locked || !peek;
      control.title = peek ? format(label + ": {label}", { label: t(peek.label) + (peek.detail ? ` (${peek.detail})` : "") })
        : t(label === "Undo" ? "Nothing to undo" : "Nothing to redo");
      control.setAttribute("aria-label", t(label));
    }
  }

  // After every apply/undo/redo: preview, affected lanes, the inspector, tab counts,
  // the undo/redo buttons, then plugins (camera rebakes run in projectChanged).
  function historyChanged({ command, direction, changes }) {
    if (!project) return;
    const tracks = new Set(), timing = new Set(), kinds = new Set();
    let selectedTouched = false, selectedTiming = false, structure = false, wholeValues = false;
    for (const change of changes) {
      const target = change.target;
      kinds.add(target.kind);
      if (target.kind === "event" || target.kind === "track") tracks.add(target.track);
      if (target.kind === "track") { structure = true; timing.add(target.track); }
      if (target.kind !== "event") continue;
      const key = change.path[0];
      // Timing and the clip name redraw the lane; value edits only toggle its marks.
      if (key === "start" || key === "duration" || key === "label") timing.add(target.track);
      if (selected && selected.track === target.track && selected.event === target.event) {
        selectedTouched = true;
        if (key !== "values" || change.path.length === 1) selectedTiming = true;
        if (key === "values" && change.path.length === 1) wholeValues = true;
      }
    }
    if (selected && !findEvent(selected.track, selected.event)) {
      selected = null;
      callPlugins("selectionChanged", null);
      selectedTouched = selectedTiming = true;
    }
    seek(time, kinds.has("soundtrack"), false);
    // The Edit tab lists tracks by edit state: rebuild it only when that set changes
    // (a slider drag on an already edited clip keeps its lanes).
    const editTab = activeTab === "edit" && (tracks.size || kinds.has("editor")) && editSignature() !== lastEditSignature;
    if (editTab || structure) renderTimeline();
    else {
      for (const id of tracks) {
        const track = project.tracks.find((item) => item.id === id);
        if (!track) continue;
        if (timing.has(id)) refreshTimelineLane(track);
        else syncLaneMarks(track);
      }
      renderTimelineTabs();
      syncTrackControls();
    }
    const quiet = direction === "do" ? quietPanel : null;
    if (selectedTouched || kinds.has("editor")) {
      const box = byId("mv-event-fields"), header = byId("mv-event-header");
      const active = activeEvent();
      if (quiet === "events" && !selectedTiming && !wholeValues && active && header && box.contains && box.contains(header)) {
        renderEventHeader(header, active.track, active.event);
      } else if (selectedTouched || direction !== "do") renderEvent();
    }
    if (kinds.has("performer") && quiet !== "performers") renderPerformers();
    if (kinds.has("soundtrack") && quiet !== "soundtrack") renderSoundtrack();
    if (kinds.has("quality")) {
      const quality = changes.filter((change) => change.target.kind === "quality");
      const preset = quality.some((change) => change.path[0] !== "values" || change.path.length === 1);
      if (quiet !== "quality" || preset) renderQuality();
      if (preset || quality.some((change) => change.path[1] === "rendering_resolution")) scene?.resize();
    }
    updateHistoryButtons();
    callPlugins("projectChanged", { reason: "history", command, direction });
  }

  // Track id → whether the extrapolation port reproduces its stored times (spec §5.3).
  function computeGates(value) {
    const gates = new Map();
    for (const track of value.tracks) gates.set(track.id, Interact.extrapolationGate(track));
    return gates;
  }

  // Costume re-import of the same MV: the native ids are identical, so every
  // edited event whose keys still match keeps its edits, and the editor layer
  // (originals, camera keys, rigs) comes along. Returns false when some edit
  // could not be carried over.
  function carryEdits(previous, next) {
    const editor = previous.editor;
    if (!editor || typeof editor !== "object") return true;
    const before = new Map(), after = new Map();
    for (const track of previous.tracks) for (const event of track.events) before.set(event.id, event);
    for (const track of next.tracks) for (const event of track.events) after.set(event.id, event);
    const keys = (values) => Object.keys(values || {}).sort().join("\n");
    let complete = true;
    for (const [id, original] of Object.entries(editor.originals || {})) {
      const current = before.get(id), fresh = after.get(id);
      if (!current) continue;
      if (!fresh || !original || keys(original.values) !== keys(fresh.values)) { complete = false; continue; }
      fresh.start = current.start;
      fresh.duration = current.duration;
      if ("label" in current) fresh.label = current.label;
      else delete fresh.label;
      fresh.values = copy(current.values);
    }
    next.editor = copy(editor);
    return complete;
  }

  function translateAria() {
    for (const node of document.querySelectorAll("#tab-mv [data-i18n-aria-label]")) node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
    for (const node of document.querySelectorAll("#tab-mv [data-mv-panel-name]")) node.textContent = t(node.dataset.mvPanelName);
  }

  function renderPanel(key) {
    const panel = panelList.find((item) => item.key === key);
    if (!panel) return;
    if (!panel.plugin) {
      ({ assets: renderAssets, performers: renderPerformers, soundtrack: renderSoundtrack, tracks: renderTracks, events: renderEvent,
        quality: renderQuality, warnings: renderWarnings })[key]?.();
      return;
    }
    // A plugin panel whose availability changed is shown or hidden first.
    const available = availablePanels().includes(key), node = panelNode(key);
    if (node && node.hidden === (available && !hidden.includes(key))) renderPanelMenu();
    const box = byId("mv-" + key + "-fields");
    if (!box || !available || typeof panel.plugin.render !== "function") return;
    try { panel.plugin.render(box, ctx); } catch (error) { console.error(error); }
  }

  function typing(target) {
    if (!target || target.isContentEditable) return !!target;
    if (target.tagName === "SELECT" || target.tagName === "TEXTAREA") return true;
    return target.tagName === "INPUT" && !["checkbox", "radio", "range", "button", "submit", "reset", "color", "file"].includes(target.type);
  }

  // Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl+Y on the MV tab, then plugin shortcuts.
  function editorKeydown(event) {
    if (!visible || !project || event.defaultPrevented || event.isComposing) return;
    const root = byId("tab-mv"), target = event.target;
    if (!(root.contains(target) || target === document.body || target === document.documentElement)) return;
    if (byId("mv-game-picker").open || ctx.locked() || typing(target)) return;
    const key = String(event.key || "").toLowerCase();
    if ((event.ctrlKey || event.metaKey) && !event.altKey && key === "z") {
      event.preventDefault();
      if (event.shiftKey) redo(); else undo();
      return;
    }
    if (event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey && key === "y") {
      event.preventDefault();
      redo();
      return;
    }
    // The user moved on (see gestureBegan); a plugin key may write through ctx.history
    // directly, which no edit() check sees.
    const owner = openGesture();
    if (owner && !pressInOwner(owner) && !(owner.keys && inOwner(owner, target))) closeGestures();
    for (const plugin of plugins) {
      if (typeof plugin.keydown !== "function") continue;
      let handled = false;
      try { handled = plugin.keydown(ctx, event) === true; } catch (error) { console.error(error); }
      if (handled) { event.preventDefault(); return; }
    }
  }

  function createContext() {
    return Object.freeze({
      project: () => project || null,
      time: () => time,
      duration: () => project ? project.duration : 0,
      playing: () => playing,
      pause,
      seek: (seconds, { audio: changeAudio = true, defer = false } = {}) => { if (project) seek(seconds, changeAudio, defer); },
      selection: () => activeEvent(),
      select: (trackId, eventId, { seek: move = true } = {}) => {
        if (!project) return;
        const found = trackId == null || eventId == null ? null : findEvent(trackId, eventId);
        if (found) chooseEvent(found.track, found.event, move);
        else clearSelection();
      },
      history,
      editor: (create = false) => {
        if (!project) return null;
        if (create && (!project.editor || typeof project.editor !== "object")) project.editor = { version: 1, originals: {} };
        return project.editor || null;
      },
      edited: (eventId) => !!project && history.editedEvents().has(eventId),
      extrapolationAuto: (track) => autoExtrapolation(track),
      scene: () => scene || null,
      t, make, button, field, numberInput, checkInput, format,
      renderTimeline: () => { if (history) history.invalidate(); renderTimeline(); },
      // For writes made outside history (a camera bake): redraws the lane, the edited
      // marks, the Edit tab when its track set changed, tab counts and the clip header.
      refreshLane: (trackId) => {
        if (!project) return;
        history.invalidate();
        if (activeTab === "edit" && editSignature() !== lastEditSignature) { renderTimeline(); }
        else {
          const track = project.tracks.find((item) => item.id === trackId);
          if (track && timelineLanes.has(trackId)) refreshTimelineLane(track);
          renderTimelineTabs();
          syncTrackControls();
        }
        const header = byId("mv-event-header"), active = activeEvent();
        if (header && active && active.track.id === trackId && byId("mv-event-fields").contains(header)) renderEventHeader(header, active.track, active.event);
      },
      renderPanel, renderEvent: () => renderEvent(),
      report,
      locked: () => !!pending || !!gameImport,
      frameRate: 60,
      snap: (seconds) => Math.round(seconds * 60) / 60,
      activeTab: () => activeTab,
      filters: () => ({ tab: activeTab, member: lastPlan ? lastPlan.member : null, search: searchText, editableOnly, group: groupFilter }),
      // Interact.attachDrag with this timeline's scale and bounds filled in.
      attachDrag: (element, options) => Interact.attachDrag(element, { pixelsPerSecond: () => pixelsPerSecond,
        bounds: () => ({ min: 0, max: project ? project.duration : 0, minLength: Interact.FRAME }), ...options }),
      // Playhead and MainCamera cut times (plus the other clip edges of trackId, except eventId).
      snapTargets: (trackId = null, eventId = null) => project ? clipSnapTargets(trackId, eventId) : [],
      // For the MV registration panel: the app's file picker, its UI language and the game import
      // (opening a registered song like any game MV).
      pickFile: (callback, title, extensions) => settings.pickFile(callback, title, extensions),
      language: () => settings.language(),
      importGame: (payload) => { if (!pending && !gameImport) runGameImport(payload); },
    });
  }

  function render() {
    translateAria();
    byId("mv-project-title").textContent = project && project.name || t("3D MV");
    renderPreviewStatus();
    renderWarnings();
    byId("mv-save").disabled = !project || !!pending;
    byId("mv-export-timeline").hidden = !(project && project.nativeTimeline);
    byId("mv-export-timeline").disabled = !!pending;
    renderPanelMenu();
    renderAssets();
    renderPerformers();
    renderSoundtrack();
    renderTracks();
    renderEvent();
    renderQuality();
    const available = availablePanels();
    for (const panel of panelList) if (panel.plugin && available.includes(panel.key)) renderPanel(panel.key);
    renderTimeline();
    updatePlayButton();
    updateHistoryButtons();
  }

  function checkedProject(data) {
    const value = data && (data.project || data);
    if (!value || value.version !== 1 || !finite(value.duration) || value.duration < 0 || !Array.isArray(value.tracks) ||
        !value.tracks.every((track) => Array.isArray(track.events) && track.events.every((event) => finite(event.start) && finite(event.duration)))) {
      throw new Error("The imported MV project is invalid.");
    }
    return value;
  }

  function ensureScene() {
    if (!scene && global.MVStudioScene) {
      scene = global.MVStudioScene.create(byId("mv-scene"), { onError: showError, onWarning: previewWarning,
        visible: visible && !document.hidden, screenFade: byId("mv-screen-fade").checked });
      scene.setVisible(visible && !document.hidden);
      if (refreshRateMode) applyRefreshRateMode();
      if (antiAliasingMode) scene.setAntiAliasing?.(true);
    }
    return scene;
  }

  // carry: a costume re-import of the same MV keeps the timeline edits and history (§5.5).
  // onLoadProgress follows the scene's model loading ({ done, total } or { phase }).
  async function commit(value, preserveTime = false, reuseOutfit = null, reuseStage = false, carry = false, onLoadProgress = null) {
    const next = checkedProject(value);
    const playhead = preserveTime ? time : 0;
    const before = project;
    pause();
    ensureScene();
    const source = resource(next.soundtrack && next.soundtrack.url);
    if (source) {
      if (audio.src !== source) audio.src = source;
    } else if (audio.hasAttribute("src")) {
      audio.removeAttribute("src"); audio.load();
    }
    const previous = selected;
    project = next;
    // Gates are decided on the data as loaded, before any carried edit.
    extrapolationGates = computeGates(next);
    let reason = preserveTime ? "reload" : "load", complete = true;
    if (carry && before && before.editor) {
      complete = carryEdits(before, next);
      reason = "reimport";
      history.invalidate();
    } else if (!preserveTime) history.clear();
    else history.invalidate();
    // The scene reports its preview notes again for the project it loads.
    previewWarnings = [];
    selected = preserveTime || reason === "reimport" ? previous : null;
    if (selected && !findEvent(selected.track, selected.event)) selected = null;
    if (!preserveTime) performerId = "";
    previewLoading = !!scene;
    try {
      const ready = scene && scene.load(next, { reuseOutfit, reuseStage, ...(onLoadProgress ? { onProgress: onLoadProgress } : {}) });
      if (scene) scene.setVisible(visible && !document.hidden);
      render();
      seek(playhead);
      if (previous && !selected) callPlugins("selectionChanged", null);
      callPlugins("projectChanged", { reason });
      await ready;
    } finally {
      previewLoading = false;
      renderPreviewStatus();
      updatePlayButton();
    }
    return complete;
  }

  async function operation(label, callback) {
    if (pending) return false;
    const controller = new AbortController();
    pending = controller;
    byId("mv-save-result").hidden = true;
    byId("mv-import-game").disabled = byId("mv-open").disabled = byId("mv-save").disabled = byId("mv-export-timeline").disabled = true;
    updateHistoryButtons();
    report(t(label));
    try { await callback(controller.signal); return true; }
    catch (error) { showError(error); return false; }
    finally {
      pending = null;
      byId("mv-import-game").disabled = byId("mv-open").disabled = false;
      byId("mv-save").disabled = !project;
      byId("mv-export-timeline").disabled = false;
      renderAssets();
      renderPerformers();
      renderSoundtrack();
      updateHistoryButtons();
    }
  }

  function open() {
    if (pending) return;
    settings.pickFile((path) => {
      if (!visible) return;
      operation("Opening MV…", async (signal) => {
        await commit(await request("open", { path }, signal));
        report("");
      });
    }, t("Open mod or project"), ["zip", "unity", "bundle", "asset", "bytes", "json", "glb"]);
  }

  function importAsset(kind, replaceActor = null) {
    if (!project || pending) return;
    // LiveCoreMemberManager.MemberMax: an MV has up to 12 performers.
    if (kind === "outfit" && replaceActor == null && (project.performers || []).length >= 12) {
      report(t("This MV already has twelve performers. Choose an existing performer to replace their outfit."), true);
      return;
    }
    const activeProject = project;
    settings.pickFile((path) => {
      if (activeProject !== project || !visible) return;
      operation("Importing MV asset…", async (signal) => {
        const response = await request("asset", { path, kind }, signal);
        if (!response.asset || typeof response.asset.id !== "string") throw new Error("The MV asset could not be imported.");
        const next = copy(project);
        next.assets = (next.assets || []).filter((asset) => asset.id !== response.asset.id);
        next.assets.push(response.asset);
        if (response.stage) next.stage = response.stage;
        if (response.performer) {
          if (replaceActor == null) next.performers = (next.performers || []).concat(response.performer);
          else next.performers = next.performers.map((actor) => actor.id === replaceActor
            ? { ...response.performer, id: actor.id, position: actor.position, themeColor: actor.themeColor,
                transform: actor.transform || response.performer.transform } : actor);
        }
        if (response.soundtrack) next.soundtrack = response.soundtrack;
        await commit(next, true, kind === "outfit" && response.performer ? replaceActor : null);
        report("");
      });
    }, t(kind === "audio" ? "Import soundtrack" : "Import MV asset"), kind === "audio"
      ? ["m4a", "mp3", "ogg", "wav", "flac"] : ["unity", "bundle", "asset", "bytes", "zip", "glb"]);
  }

  function saveResult(endpoint, pendingLabel, doneLabel) {
    if (!project || pending) return;
    operation(pendingLabel, async (signal) => {
      // Plugins finish pending work (camera bakes) or refuse with an Error first.
      for (const plugin of plugins) {
        const hook = plugin[endpoint === "export-timeline" ? "beforeExport" : "beforeSave"];
        if (typeof hook === "function") await hook.call(plugin, ctx);
        if (signal.aborted) throw new DOMException("The MV request was cancelled.", "AbortError");
      }
      const snapshot = copy(project);
      const receipt = await request(endpoint, { project: snapshot }, signal);
      const href = resource(receipt.download);
      if (!href) throw new Error("The MV project could not be saved.");
      const result = byId("mv-save-result"), name = basename(receipt.path);
      result.replaceChildren(make("a", name || t("Download MV project"), { href, download: name, title: text(receipt.path) }));
      if (receipt.path && global.ElichikaPlatform && ElichikaPlatform.supports("reveal")) {
        result.append(button(t("Show in Finder"), () => ElichikaPlatform.request("reveal", { path: receipt.path }).catch(showError)));
      }
      result.hidden = false;
      report(t(doneLabel));
    });
  }

  function save() { return saveResult("save", "Saving MV project…", "MV project saved."); }

  function syncVariants() {
    const song = songs.find((item) => text(item.id) === byId("mv-game-song").value);
    const variants = byId("mv-game-variant");
    replaceOptions(variants, song && song.variants || [], variants.value);
    byId("mv-game-download").checked = false;
    byId("mv-game-load").disabled = !song || !variants.value || !!catalogRequest;
  }

  function foldSearch(value) { return text(value).normalize("NFKC").toLocaleLowerCase(settings.language()); }

  function filterCatalog() {
    if (catalogRequest) return;
    const query = foldSearch(byId("mv-game-search").value.trim());
    const select = byId("mv-game-song");
    songs = catalogIndex.filter((entry) => !query || entry.search.includes(query)).map((entry) => entry.song);
    replaceOptions(select, songs.map((song) => ({ id: song.id, label: song.title + (song.mvOnly ? " · " + t("MV only") : "") })), select.value);
    byId("mv-game-status").textContent = songs.length ? "" : t("No matching MVs.");
    syncVariants();
  }

  async function loadCatalog() {
    const dialog = byId("mv-game-picker");
    if (!dialog.open) return;
    if (catalogRequest) catalogRequest.abort();
    const controller = new AbortController();
    catalogRequest = controller;
    const region = byId("mv-game-region"), platform = byId("mv-game-platform"), song = byId("mv-game-song");
    const status = byId("mv-game-status");
    status.textContent = t("Loading MVs…");
    byId("mv-game-load").disabled = true;
    const native = global.ElichikaPlatform && ElichikaPlatform.info().platform === "macos";
    const query = new URLSearchParams({ region: region.value || (settings.language() === "ja" ? "jp" : "gl"),
      platform: platform.value || (native ? "ios" : "android") });
    try {
      const data = await request("catalog?" + query, undefined, controller.signal);
      if (catalogRequest !== controller || !dialog.open) return;
      replaceOptions(region, data.regions || [], data.region || region.value);
      replaceOptions(platform, data.platforms || [], data.platform || platform.value);
      // A local Elichika player database: follow that player's saved MV decks. A lone
      // player is preselected until one is chosen; a reload never overrides a choice,
      // including "New player". The import records the deck and player it used.
      const players = Array.isArray(data.players) ? data.players : [], player = byId("mv-game-player");
      replaceOptions(player, players.map((item) => ({ id: item.id, label: text(item.name) + " (" + text(item.id) + ")" })),
        !player.dataset.chosen && players.length === 1 ? players[0].id : player.value, t("New player"));
      byId("mv-game-player-field").hidden = !players.length;
      catalogIndex = (Array.isArray(data.songs) ? data.songs : []).map((song) => ({ song,
        search: foldSearch([song.id, song.title, ...(song.variants || []).flatMap((variant) => [variant.id, variant.label])].join("\n")) }));
      catalogRequest = null;
      filterCatalog();
    } catch (error) {
      if (catalogRequest === controller && error.name !== "AbortError") {
        catalogIndex = []; songs = []; song.replaceChildren(); status.textContent = t(error.message);
      }
    } finally {
      if (catalogRequest === controller) { catalogRequest = null; syncVariants(); }
    }
  }

  function showCatalog() {
    if (pending) return;
    const picker = byId("mv-game-picker");
    byId("mv-game-download").checked = false;
    picker.showModal();
    loadCatalog();
  }

  function blockImportEdit(event) {
    if (event.type === "keydown" && event.key === "Tab") return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  function lockGameEditing(locked) {
    updateHistoryButtons();
    for (const id of ["mv-inspector", "mv-timeline-scroll", "mv-timeline-nav"]) {
      const panel = byId(id);
      if ("inert" in panel) panel.inert = locked;
      else {
        if (locked && panel.contains(document.activeElement)) document.activeElement.blur();
        const method = locked ? "addEventListener" : "removeEventListener";
        for (const type of ["click", "pointerdown", "keydown", "beforeinput", "input", "change"]) {
          panel[method](type, blockImportEdit, true);
        }
      }
    }
  }

  function isCurrentGameImport(load) {
    return gameImport === load && !load.controller.signal.aborted;
  }

  function discardStage(load) {
    if (load.stageRequested) scene?.cancelStagePreparation?.();
    load.stageRequested = load.stageReady = false;
  }

  function cancelGameImport() {
    if (!gameImport || gameImport.finishing) return;
    gameImport.cancelRequested = true;
    gameImport.progress?.cancel();
    renderImportProgress(gameImport);
    gameImport.controller.abort();
    discardStage(gameImport);
    renderPreviewStatus();
  }

  // The import progress card over the preview: a centred card until the stage
  // shows, then a strip along its bottom edge. #mv-status repeats the step for
  // screen readers, and only when the step changes.
  function renderImportProgress(load) {
    const card = byId("mv-import-progress");
    if (!card || !load || gameImport !== load) return;
    const Progress = global.MVStudioImportProgress;
    const view = load.progress ? load.progress.snapshot(performance.now()) : null;
    const bar = byId("mv-import-bar"), percent = byId("mv-import-percent"), cancel = byId("mv-import-cancel");
    let step = t("Preparing MV from game…");
    if (view) {
      step = format(view.step[0], view.step[1]) + (view.cached ? " · " + t("Reused from cache") : "");
      const details = [];
      if (view.phase) details.push(format(view.phase[0], view.phase[1]));
      if (view.members) details.push(format("Members done {done}/{count}", { done: view.members[0], count: view.members[1] }));
      if (view.bytes) details.push(format("Game data {read}/{total} MB",
        { read: Progress.megabytes(Math.min(view.bytes[0], view.bytes[1])), total: Progress.megabytes(view.bytes[1]) }));
      details.push(Progress.formatElapsed(view.elapsed));
      byId("mv-import-detail").textContent = details.join(" · ");
      if (view.determinate) {
        bar.value = view.percent;
        percent.textContent = format("{percent}%", { percent: view.percent });
        bar.setAttribute("aria-valuetext", format("{percent}%", { percent: view.percent }) + " · " + step);
      } else {
        bar.removeAttribute("value");
        percent.textContent = "";
        bar.setAttribute("aria-valuetext", step);
      }
    }
    if (load.cancelRequested) step = t("Cancelling…");
    byId("mv-import-step").textContent = step;
    cancel.textContent = t(load.cancelRequested ? "Cancelling…" : "Cancel import");
    cancel.disabled = !!load.cancelRequested || load.finishing;
    card.classList.toggle("mv-import-strip", !!load.stageReady);
    card.hidden = false;
    if (load.statusText !== step) {
      load.statusText = step;
      report(step);
    }
  }

  function startImportProgress(load) {
    load.progress = global.MVStudioImportProgress ? global.MVStudioImportProgress.create(performance.now()) : null;
    load.timer = setInterval(() => renderImportProgress(load), 1000);
    renderImportProgress(load);
  }

  function stopImportProgress(load) {
    clearInterval(load.timer);
    const card = byId("mv-import-progress");
    if (card && gameImport === load) card.hidden = true;
  }

  async function showGameStage(load, preview) {
    if (!isCurrentGameImport(load) || load.finishing || !visible || document.hidden) return;
    try {
      const target = ensureScene();
      if (!target?.prepareStage) return;
      load.stageRequested = true;
      const ready = await target.prepareStage(preview);
      if (isCurrentGameImport(load) && !load.finishing && ready) {
        load.stageReady = true;
        load.progress?.stage();
        renderImportProgress(load);
        renderPreviewStatus();
      }
    } catch (_) {
      if (isCurrentGameImport(load) && !load.finishing) discardStage(load);
    }
  }

  function importGame() {
    const song = byId("mv-game-song"), variant = byId("mv-game-variant");
    if (!song.value || !variant.value || catalogRequest) return;
    const choice = songs.find((item) => text(item.id) === song.value);
    const version = choice && choice.variants.find((item) => text(item.id ?? item.value) === variant.value);
    if (!choice || !version) return;
    const payload = { region: byId("mv-game-region").value, platform: byId("mv-game-platform").value,
      liveId: choice.id, assetId: version.id ?? version.value, download: byId("mv-game-download").checked };
    // The client's first deck tab is Customize; only another choice is sent.
    const deckType = Number(byId("mv-game-deck").value) || 2, player = Number(byId("mv-game-player").value) || 0;
    if (deckType !== 2 || player) payload.deck = { deckType, ...(player ? { userId: player } : {}) };
    byId("mv-game-picker").close();
    runGameImport(payload);
  }

  function runGameImport(payload, carry = false) {
    if (pending) return;
    lastGamePayload = payload;
    operation("Preparing MV from game…", async (signal) => {
      const load = { controller: pending, stageRequested: false, stageReady: false, finishing: false };
      gameImport = load;
      pause();
      lockGameEditing(true);
      startImportProgress(load);
      renderPreviewStatus();
      let committed = false;
      const requireCurrent = () => {
        if (!isCurrentGameImport(load)) throw new DOMException("The MV import was cancelled.", "AbortError");
      };
      const progressed = (update) => {
        if (!isCurrentGameImport(load)) return;
        if (update) load.progress?.record(update);
        renderImportProgress(load);
      };
      try {
        requireCurrent();
        let imported = await requestGameStream(payload, signal, (preview) => showGameStage(load, preview), progressed);
        requireCurrent();
        if (imported === null) imported = checkedProject(await request("game", payload, signal));
        requireCurrent();
        load.finishing = true;
        load.progress?.complete();
        renderImportProgress(load);
        const complete = await commit(imported, false, null, load.stageRequested, carry, (update) => {
          load.progress?.page(update);
          renderImportProgress(load);
        });
        committed = true;
        report(complete ? "" : t("Some timeline edits could not be carried over."), !complete);
      } catch (error) {
        if (load.cancelRequested && !load.finishing) report(t("MV import cancelled."));
        if (!load.finishing) requireCurrent();
        throw error;
      } finally {
        stopImportProgress(load);
        if (!committed) discardStage(load);
        gameImport = null;
        lockGameEditing(false);
        renderPreviewStatus();
        updatePlayButton();
      }
    });
  }

  function setupTimelineResizer(scroll) {
    const grip = byId("mv-timeline-resizer"), key = "elichika.mv.timelineHeight.v1", minimum = 62;
    const workspace = byId("mv-workspace"), inspector = byId("mv-inspector"), timeline = scroll.parentElement;
    const toolbar = timeline.querySelector(".mv-timeline-toolbar");
    const portrait = global.matchMedia("(max-width: 640px) and (orientation: portrait)");
    let preferred = null, drag = null, resizeFrame = 0, nextHeight, maximum = minimum;
    try {
      const saved = Number(localStorage.getItem(key));
      if (finite(saved) && saved >= minimum) preferred = saved;
    } catch (_) {}

    function syncValue() {
      grip.setAttribute("aria-valuenow", Math.max(minimum, scroll.clientHeight));
    }

    function reflectHeight() {
      const height = preferred === null ? null : clamp(preferred, minimum, maximum);
      const size = height === null ? "" : `${height}px`;
      if (scroll.style.getPropertyValue("--mv-timeline-height") !== size) {
        if (size) scroll.style.setProperty("--mv-timeline-height", size);
        else scroll.style.removeProperty("--mv-timeline-height");
      }
      if (height === null) syncValue();
      else grip.setAttribute("aria-valuenow", height);
    }

    function syncBounds() {
      const available = workspace.clientHeight;
      if (!available) return;
      const style = global.getComputedStyle(workspace);
      const gap = parseFloat(style.rowGap);
      const previewMinimum = parseFloat(style.getPropertyValue("--mv-preview-min"));
      const inspectorHeight = portrait.matches && !inspector.hidden ? inspector.offsetHeight + gap : 0;
      const borders = timeline.offsetHeight - timeline.clientHeight;
      maximum = Math.max(minimum, Math.floor(available - gap - previewMinimum - inspectorHeight -
        toolbar.offsetHeight - grip.offsetHeight - borders));
      const limit = `${maximum}px`;
      if (scroll.style.getPropertyValue("--mv-timeline-limit") !== limit) scroll.style.setProperty("--mv-timeline-limit", limit);
      grip.setAttribute("aria-valuemax", maximum);
      reflectHeight();
    }

    function saveHeight() {
      try {
        if (preferred === null) localStorage.removeItem(key);
        else localStorage.setItem(key, String(preferred));
      } catch (_) {}
    }

    function applyDrag() {
      resizeFrame = 0;
      preferred = clamp(Math.round(nextHeight), minimum, maximum);
      reflectHeight();
    }

    grip.setAttribute("aria-valuemin", minimum);
    grip.addEventListener("pointerdown", (event) => {
      if (drag || event.button !== 0) return;
      event.preventDefault();
      grip.focus({ preventScroll: true });
      drag = { id: event.pointerId, y: event.clientY, height: scroll.clientHeight, moved: false };
      grip.setPointerCapture(event.pointerId);
      grip.classList.add("mv-dragging");
    });
    grip.addEventListener("pointermove", (event) => {
      if (drag?.id !== event.pointerId) return;
      nextHeight = drag.height + drag.y - event.clientY;
      drag.moved ||= event.clientY !== drag.y;
      if (drag.moved && !resizeFrame) resizeFrame = requestAnimationFrame(applyDrag);
    });
    function finishDrag(event) {
      if (drag?.id !== event.pointerId) return;
      if (resizeFrame) {
        cancelAnimationFrame(resizeFrame);
        applyDrag();
      }
      if (drag.moved) saveHeight();
      drag = null;
      grip.classList.remove("mv-dragging");
    }
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) grip.addEventListener(type, finishDrag);
    grip.addEventListener("keydown", (event) => {
      if (drag) return;
      const step = event.shiftKey ? 48 : 16;
      if (event.key === "Home") preferred = null;
      else if (event.key === "End") preferred = maximum;
      else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        preferred = clamp(scroll.clientHeight + (event.key === "ArrowUp" ? step : -step), minimum, maximum);
      } else return;
      event.preventDefault();
      reflectHeight();
      saveHeight();
    });
    if (global.ResizeObserver) {
      const boundsObserver = new ResizeObserver(syncBounds);
      for (const element of [workspace, toolbar, grip]) boundsObserver.observe(element);
    }
    global.addEventListener("resize", syncBounds);
    syncBounds();
    return { syncBounds, syncValue };
  }

  function setVisible(value) {
    if (!settings) return;
    visible = value;
    if (scene) scene.setVisible(visible && !document.hidden);
    if (!visible) {
      pause();
      if (byId("mv-game-picker").open) byId("mv-game-picker").close();
    }
    if (visible) {
      timelineResizer.syncBounds();
      renderTimeline();
    }
  }

  // Editor plugins: sorted by order then id, attached once, their panels placed after "Selected event".
  function mountPlugins() {
    panelList = panelKeys.map((key, index) => ({ key, name: panelNames[index], plugin: null }));
    plugins = (Array.isArray(global.MVStudioPlugins) ? global.MVStudioPlugins : []).filter((plugin) => plugin && typeof plugin === "object")
      .sort((first, second) => (finite(first.order) ? first.order : 0) - (finite(second.order) ? second.order : 0) ||
        text(first.id).localeCompare(text(second.id)));
    for (const plugin of plugins) {
      if (typeof plugin.attach !== "function") continue;
      try { plugin.attach(ctx); } catch (error) { console.error(`MV Studio plugin ${plugin.id}: attach`, error); }
    }
    let anchor = byId("mv-events"), at = panelList.findIndex((panel) => panel.key === "events") + 1;
    for (const plugin of plugins) {
      let list = plugin.panels;
      if (typeof list === "function") { try { list = list.call(plugin, ctx); } catch (error) { console.error(error); list = null; } }
      if (!Array.isArray(list)) continue;
      for (const panel of list) {
        if (!panel || typeof panel.key !== "string" || !/^[A-Za-z0-9_-]+$/.test(panel.key) || panelList.some((item) => item.key === panel.key)) continue;
        const name = text(panel.name || panel.key);
        const details = make("details", null, { id: "mv-panel-" + panel.key, "data-mv-panel": panel.key });
        details.open = !!panel.open;
        details.append(make("summary", t(name), { "data-mv-panel-name": name }),
          make("div", null, { class: "mv-panel-content", id: "mv-" + panel.key + "-fields" }));
        anchor.after(details);
        anchor = details;
        panelList.splice(at++, 0, { key: panel.key, name, plugin: panel });
      }
    }
  }

  // Timeline tabs, member chips and the name search (tab and filters are remembered per session).
  function mountTimelineNav() {
    const stored = session(tabKey);
    if (Tabs.TAB_IDS.includes(stored)) preferredTab = stored;
    const member = Number(session(memberKey));
    preferredMember = Number.isInteger(member) && member > 0 ? member : null;
    searchText = text(session(searchKey)).slice(0, 120);
    editableOnly = session(editableKey) === "1";
    const search = byId("mv-track-search");
    search.value = searchText;
    search.addEventListener("input", () => {
      searchText = search.value.slice(0, 120);
      session(searchKey, searchText || null);
      if (!renderQueued) renderQueued = requestAnimationFrame(() => { renderQueued = 0; renderTimeline(); });
    });
    const tabs = byId("mv-timeline-tabs"), members = byId("mv-member-filter");
    Tabs.roving(tabs, "[role=tab]", (item) => item.dataset.mvTab, selectTab);
    Tabs.roving(members, "[role=radio]", (item) => item.dataset.mvMember, selectMember, { vertical: true });
    byId("mv-undo").addEventListener("click", undo);
    byId("mv-redo").addEventListener("click", redo);
    document.addEventListener("keydown", editorKeydown);
  }

  function mount(options) {
    if (settings) return;
    settings = options;
    seekInput = byId("mv-seek");
    timeOutput = byId("mv-time");
    history = global.MVStudioEditHistory.create({ getProject: () => project, onChange: historyChanged, limit: 200, onBegin: gestureBegan,
      compareView: (track, event) => {
        const view = global.MVStudioEditHistory.editedView(event);
        // Extrapolation times of a gated track are derived from the clip timing.
        if (view && view.values && autoExtrapolation(track)) {
          const values = { ...view.values };
          delete values.preExtrapolationTime;
          delete values.postExtrapolationTime;
          view.values = values;
        }
        return view;
      } });
    watchGestures();
    ctx = createContext();
    mountPlugins();
    const timelineScroll = byId("mv-timeline-scroll");
    timelineResizer = setupTimelineResizer(timelineScroll);
    try { hidden = (JSON.parse(localStorage.getItem("elichika.mv.panels.v1")) || []).filter((key) => panelList.some((panel) => panel.key === key)); } catch (_) {}
    mountTimelineNav();
    byId("mv-import-game").addEventListener("click", showCatalog);
    byId("mv-game-close").addEventListener("click", () => byId("mv-game-picker").close());
    byId("mv-open").addEventListener("click", open);
    byId("mv-save").addEventListener("click", save);
    byId("mv-export-timeline").addEventListener("click", () => {
      if (project && project.nativeTimeline) saveResult("export-timeline", "Exporting native timeline…", "Native timeline exported.");
    });
    byId("mv-rewind").addEventListener("click", () => { pause(); seek(0); });
    byId("mv-play").addEventListener("click", togglePlayback);
    byId("mv-camera-mode").addEventListener("change", (event) => { if (scene) scene.setCamera(event.target.value); });
    byId("mv-screen-fade").addEventListener("change", (event) => { if (scene) scene.setScreenFade(event.target.checked); });
    byId("mv-frame-scene").addEventListener("click", () => {
      if (!scene) return;
      byId("mv-camera-mode").value = "orbit";
      scene.setCamera("orbit");
      scene.frameAll();
    });
    seekInput.addEventListener("input", (event) => seek(event.target.valueAsNumber, true, true));
    seekInput.addEventListener("change", flushScrub);
    byId("mv-zoom").addEventListener("change", renderTimeline);
    byId("mv-game-region").addEventListener("change", loadCatalog);
    byId("mv-game-platform").addEventListener("change", loadCatalog);
    byId("mv-game-song").addEventListener("change", syncVariants);
    byId("mv-game-variant").addEventListener("change", () => { byId("mv-game-download").checked = false; });
    byId("mv-game-player").addEventListener("change", (event) => { event.target.dataset.chosen = "1"; });
    byId("mv-game-search").addEventListener("input", filterCatalog);
    byId("mv-game-load").addEventListener("click", importGame);
    byId("mv-import-cancel").addEventListener("click", cancelGameImport);
    byId("mv-game-picker").addEventListener("close", () => {
      if (catalogRequest) catalogRequest.abort();
      catalogRequest = null;
      catalogIndex = [];
    });
    document.addEventListener("visibilitychange", () => {
      if (scene) scene.setVisible(visible && !document.hidden);
      if (document.hidden) pause();
    });
    global.addEventListener("pagehide", (event) => {
      pause();
      if (event.persisted) return;
      cancelGameImport();
      if (pending) pending.abort();
      if (catalogRequest) catalogRequest.abort();
      if (scene) scene.dispose();
    });
    let width = -1;
    resizeObserver = global.ResizeObserver && new ResizeObserver(() => {
      if (!visible) return;
      const next = timelineScroll.clientWidth;
      if (next !== width) { width = next; renderTimeline(); }
      timelineResizer.syncValue();
    });
    if (resizeObserver) resizeObserver.observe(timelineScroll);
    render();
  }

  global.MVStudio = Object.freeze({ mount, setVisible, updateLanguage: () => { if (settings) render(); }, open, save,
    getState: () => {
      const size = history ? history.size() : { undo: 0, redo: 0 };
      return { visible, playing, time, selection: selected && { ...selected }, project: project && copy(project), tab: activeTab,
        filters: { member: lastPlan ? lastPlan.member : null, search: searchText, editableOnly, group: groupFilter },
        history: { undo: size.undo, redo: size.redo, undoLabel: history?.peekUndo()?.label || null, redoLabel: history?.peekRedo()?.label || null,
          version: history ? history.version : 0 } };
    } });
})(window);
